// MinimalCppEngine: a tiny self-contained UCI chess engine.
//
// Speaks the minimal UCI subset over stdin/stdout plus the "go perft <depth>"
// extension. Move generation is fully legal: pseudo-legal moves are produced
// and then filtered by checking whether the side-to-move's king is attacked
// after the move. Supports pawn pushes (single/double), captures, en passant,
// all four promotions, knight/bishop/rook/queen/king moves, and castling with
// the standard legality rules. Only standard C++ headers are used.

#include <array>
#include <cctype>
#include <cstdint>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

// 0x88 board. A square index is rank*16 + file. A square is on the board iff
// (sq & 0x88) == 0. This makes off-board detection during sliding/leaping
// generation trivial.
constexpr int OFFBOARD = 0x88;

// Piece codes. 0 = empty. White pieces are 1..6, black are 9..14. The color
// bit is 0x08; the type is the low 3 bits.
enum Piece : int {
    EMPTY = 0,
    W_P = 1, W_N = 2, W_B = 3, W_R = 4, W_Q = 5, W_K = 6,
    B_P = 9, B_N = 10, B_B = 11, B_R = 12, B_Q = 13, B_K = 14,
};

constexpr int COLOR_BIT = 0x08;
constexpr int TYPE_MASK = 0x07;

inline bool isWhite(int p) { return p != EMPTY && (p & COLOR_BIT) == 0; }
inline bool isBlack(int p) { return (p & COLOR_BIT) != 0; }
inline int  pieceType(int p) { return p & TYPE_MASK; }  // 1..6

enum Type : int { T_PAWN = 1, T_KNIGHT = 2, T_BISHOP = 3, T_ROOK = 4, T_QUEEN = 5, T_KING = 6 };

inline int fileOf(int sq) { return sq & 7; }
inline int rankOf(int sq) { return sq >> 4; }
inline int sqFromFR(int file, int rank) { return rank * 16 + file; }

// Castling-rights bitmask.
constexpr int CR_WK = 1;  // white king-side
constexpr int CR_WQ = 2;  // white queen-side
constexpr int CR_BK = 4;  // black king-side
constexpr int CR_BQ = 8;  // black queen-side

struct Board {
    std::array<int, 128> sq{};   // piece on each 0x88 square
    bool whiteToMove = true;
    int castling = 0;            // CR_* bitmask
    int ep = -1;                 // en-passant target square (0x88), or -1
    // halfmove/fullmove clocks are parsed but irrelevant to perft/legality here.
};

// Direction offsets in 0x88.
constexpr int N_OFF = 16, S_OFF = -16, E_OFF = 1, W_OFF = -1;
constexpr int NE_OFF = 17, NW_OFF = 15, SE_OFF = -15, SW_OFF = -17;

const int KNIGHT_OFFS[8] = {33, 31, 18, 14, -33, -31, -18, -14};
const int KING_OFFS[8]   = {N_OFF, S_OFF, E_OFF, W_OFF, NE_OFF, NW_OFF, SE_OFF, SW_OFF};
const int BISHOP_OFFS[4] = {NE_OFF, NW_OFF, SE_OFF, SW_OFF};
const int ROOK_OFFS[4]   = {N_OFF, S_OFF, E_OFF, W_OFF};

struct Move {
    int from;
    int to;
    int promo;     // 0, or type T_QUEEN/T_ROOK/T_BISHOP/T_KNIGHT
    int flag;      // 0 normal, 1 double-push, 2 en-passant, 3 castle
};

constexpr int FLAG_NORMAL = 0, FLAG_DOUBLE = 1, FLAG_EP = 2, FLAG_CASTLE = 3;

// ---------------------------------------------------------------------------
// FEN parsing
// ---------------------------------------------------------------------------

int charToPiece(char c) {
    switch (c) {
        case 'P': return W_P; case 'N': return W_N; case 'B': return W_B;
        case 'R': return W_R; case 'Q': return W_Q; case 'K': return W_K;
        case 'p': return B_P; case 'n': return B_N; case 'b': return B_B;
        case 'r': return B_R; case 'q': return B_Q; case 'k': return B_K;
        default:  return EMPTY;
    }
}

int squareFromName(const std::string& s) {
    if (s.size() < 2) return -1;
    int file = s[0] - 'a';
    int rank = s[1] - '1';
    if (file < 0 || file > 7 || rank < 0 || rank > 7) return -1;
    return sqFromFR(file, rank);
}

bool parseFen(const std::string& fen, Board& b) {
    b = Board{};
    std::istringstream iss(fen);
    std::string placement, active, castle, eptarget;
    if (!(iss >> placement >> active >> castle >> eptarget)) return false;
    // halfmove/fullmove optional; ignore.

    int rank = 7, file = 0;
    for (char c : placement) {
        if (c == '/') { rank--; file = 0; continue; }
        if (std::isdigit(static_cast<unsigned char>(c))) {
            file += c - '0';
            continue;
        }
        int p = charToPiece(c);
        if (p == EMPTY) return false;
        if (rank < 0 || rank > 7 || file < 0 || file > 7) return false;
        b.sq[sqFromFR(file, rank)] = p;
        file++;
    }

    b.whiteToMove = (active == "w");

    b.castling = 0;
    if (castle != "-") {
        for (char c : castle) {
            switch (c) {
                case 'K': b.castling |= CR_WK; break;
                case 'Q': b.castling |= CR_WQ; break;
                case 'k': b.castling |= CR_BK; break;
                case 'q': b.castling |= CR_BQ; break;
                default: break;
            }
        }
    }

    b.ep = (eptarget == "-") ? -1 : squareFromName(eptarget);
    return true;
}

// ---------------------------------------------------------------------------
// Attack detection
// ---------------------------------------------------------------------------

// Is `sq` attacked by the side whose color is `byWhite`?
bool isSquareAttacked(const Board& b, int sq, bool byWhite) {
    // Pawn attacks. A white pawn on x attacks x+NE and x+NW. So `sq` is attacked
    // by a white pawn sitting one rank below-left/right of it.
    if (byWhite) {
        int s1 = sq + SE_OFF;  // pawn would be down-right
        int s2 = sq + SW_OFF;  // pawn would be down-left
        if (!(s1 & OFFBOARD) && b.sq[s1] == W_P) return true;
        if (!(s2 & OFFBOARD) && b.sq[s2] == W_P) return true;
    } else {
        int s1 = sq + NE_OFF;
        int s2 = sq + NW_OFF;
        if (!(s1 & OFFBOARD) && b.sq[s1] == B_P) return true;
        if (!(s2 & OFFBOARD) && b.sq[s2] == B_P) return true;
    }

    // Knight attacks.
    int wantN = byWhite ? W_N : B_N;
    for (int off : KNIGHT_OFFS) {
        int t = sq + off;
        if (!(t & OFFBOARD) && b.sq[t] == wantN) return true;
    }

    // King attacks.
    int wantK = byWhite ? W_K : B_K;
    for (int off : KING_OFFS) {
        int t = sq + off;
        if (!(t & OFFBOARD) && b.sq[t] == wantK) return true;
    }

    // Bishop/queen diagonal sliders.
    int wantB = byWhite ? W_B : B_B;
    int wantQ = byWhite ? W_Q : B_Q;
    for (int off : BISHOP_OFFS) {
        int t = sq + off;
        while (!(t & OFFBOARD)) {
            int p = b.sq[t];
            if (p != EMPTY) {
                if (p == wantB || p == wantQ) return true;
                break;
            }
            t += off;
        }
    }

    // Rook/queen orthogonal sliders.
    int wantR = byWhite ? W_R : B_R;
    for (int off : ROOK_OFFS) {
        int t = sq + off;
        while (!(t & OFFBOARD)) {
            int p = b.sq[t];
            if (p != EMPTY) {
                if (p == wantR || p == wantQ) return true;
                break;
            }
            t += off;
        }
    }

    return false;
}

int findKing(const Board& b, bool white) {
    int want = white ? W_K : B_K;
    for (int r = 0; r < 8; r++)
        for (int f = 0; f < 8; f++) {
            int s = sqFromFR(f, r);
            if (b.sq[s] == want) return s;
        }
    return -1;
}

bool inCheck(const Board& b, bool white) {
    int k = findKing(b, white);
    if (k < 0) return false;
    return isSquareAttacked(b, k, !white);
}

// ---------------------------------------------------------------------------
// Pseudo-legal move generation
// ---------------------------------------------------------------------------

void addPawnMove(std::vector<Move>& out, int from, int to, int flag, bool promo) {
    if (promo) {
        out.push_back({from, to, T_QUEEN, flag});
        out.push_back({from, to, T_ROOK, flag});
        out.push_back({from, to, T_BISHOP, flag});
        out.push_back({from, to, T_KNIGHT, flag});
    } else {
        out.push_back({from, to, 0, flag});
    }
}

void genPseudoLegal(const Board& b, std::vector<Move>& out) {
    out.clear();
    bool white = b.whiteToMove;

    for (int r = 0; r < 8; r++) {
        for (int f = 0; f < 8; f++) {
            int from = sqFromFR(f, r);
            int p = b.sq[from];
            if (p == EMPTY) continue;
            if (white && !isWhite(p)) continue;
            if (!white && !isBlack(p)) continue;

            int type = pieceType(p);

            if (type == T_PAWN) {
                int fwd = white ? N_OFF : S_OFF;
                int startRank = white ? 1 : 6;
                int promoRank = white ? 7 : 0;

                int one = from + fwd;
                if (!(one & OFFBOARD) && b.sq[one] == EMPTY) {
                    bool promo = (rankOf(one) == promoRank);
                    addPawnMove(out, from, one, FLAG_NORMAL, promo);
                    if (rankOf(from) == startRank) {
                        int two = one + fwd;
                        if (!(two & OFFBOARD) && b.sq[two] == EMPTY)
                            addPawnMove(out, from, two, FLAG_DOUBLE, false);
                    }
                }
                // Captures (and en passant).
                int capOffs[2] = {white ? NE_OFF : SE_OFF, white ? NW_OFF : SW_OFF};
                for (int co : capOffs) {
                    int to = from + co;
                    if (to & OFFBOARD) continue;
                    int target = b.sq[to];
                    if (target != EMPTY) {
                        bool enemy = white ? isBlack(target) : isWhite(target);
                        if (enemy) {
                            bool promo = (rankOf(to) == promoRank);
                            addPawnMove(out, from, to, FLAG_NORMAL, promo);
                        }
                    } else if (to == b.ep && b.ep >= 0) {
                        out.push_back({from, to, 0, FLAG_EP});
                    }
                }
            } else if (type == T_KNIGHT) {
                for (int off : KNIGHT_OFFS) {
                    int to = from + off;
                    if (to & OFFBOARD) continue;
                    int target = b.sq[to];
                    if (target == EMPTY ||
                        (white ? isBlack(target) : isWhite(target)))
                        out.push_back({from, to, 0, FLAG_NORMAL});
                }
            } else if (type == T_KING) {
                for (int off : KING_OFFS) {
                    int to = from + off;
                    if (to & OFFBOARD) continue;
                    int target = b.sq[to];
                    if (target == EMPTY ||
                        (white ? isBlack(target) : isWhite(target)))
                        out.push_back({from, to, 0, FLAG_NORMAL});
                }
                // Castling. Verify rights, empty squares, and that the king is
                // not in check now and does not pass through an attacked square.
                if (white && from == sqFromFR(4, 0)) {
                    if ((b.castling & CR_WK) &&
                        b.sq[sqFromFR(5, 0)] == EMPTY && b.sq[sqFromFR(6, 0)] == EMPTY &&
                        b.sq[sqFromFR(7, 0)] == W_R &&
                        !isSquareAttacked(b, sqFromFR(4, 0), false) &&
                        !isSquareAttacked(b, sqFromFR(5, 0), false) &&
                        !isSquareAttacked(b, sqFromFR(6, 0), false))
                        out.push_back({from, sqFromFR(6, 0), 0, FLAG_CASTLE});
                    if ((b.castling & CR_WQ) &&
                        b.sq[sqFromFR(3, 0)] == EMPTY && b.sq[sqFromFR(2, 0)] == EMPTY &&
                        b.sq[sqFromFR(1, 0)] == EMPTY &&
                        b.sq[sqFromFR(0, 0)] == W_R &&
                        !isSquareAttacked(b, sqFromFR(4, 0), false) &&
                        !isSquareAttacked(b, sqFromFR(3, 0), false) &&
                        !isSquareAttacked(b, sqFromFR(2, 0), false))
                        out.push_back({from, sqFromFR(2, 0), 0, FLAG_CASTLE});
                } else if (!white && from == sqFromFR(4, 7)) {
                    if ((b.castling & CR_BK) &&
                        b.sq[sqFromFR(5, 7)] == EMPTY && b.sq[sqFromFR(6, 7)] == EMPTY &&
                        b.sq[sqFromFR(7, 7)] == B_R &&
                        !isSquareAttacked(b, sqFromFR(4, 7), true) &&
                        !isSquareAttacked(b, sqFromFR(5, 7), true) &&
                        !isSquareAttacked(b, sqFromFR(6, 7), true))
                        out.push_back({from, sqFromFR(6, 7), 0, FLAG_CASTLE});
                    if ((b.castling & CR_BQ) &&
                        b.sq[sqFromFR(3, 7)] == EMPTY && b.sq[sqFromFR(2, 7)] == EMPTY &&
                        b.sq[sqFromFR(1, 7)] == EMPTY &&
                        b.sq[sqFromFR(0, 7)] == B_R &&
                        !isSquareAttacked(b, sqFromFR(4, 7), true) &&
                        !isSquareAttacked(b, sqFromFR(3, 7), true) &&
                        !isSquareAttacked(b, sqFromFR(2, 7), true))
                        out.push_back({from, sqFromFR(2, 7), 0, FLAG_CASTLE});
                }
            } else {
                // Sliding pieces.
                const int* offs;
                int n;
                if (type == T_BISHOP) { offs = BISHOP_OFFS; n = 4; }
                else if (type == T_ROOK) { offs = ROOK_OFFS; n = 4; }
                else { offs = KING_OFFS; n = 8; }  // queen: all 8 directions
                for (int i = 0; i < n; i++) {
                    int off = offs[i];
                    int to = from + off;
                    while (!(to & OFFBOARD)) {
                        int target = b.sq[to];
                        if (target == EMPTY) {
                            out.push_back({from, to, 0, FLAG_NORMAL});
                        } else {
                            if (white ? isBlack(target) : isWhite(target))
                                out.push_back({from, to, 0, FLAG_NORMAL});
                            break;
                        }
                        to += off;
                    }
                }
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Make move (returns whether resulting position leaves mover's king safe)
// ---------------------------------------------------------------------------

int promoPiece(int type, bool white) {
    int base;
    switch (type) {
        case T_QUEEN:  base = T_QUEEN; break;
        case T_ROOK:   base = T_ROOK; break;
        case T_BISHOP: base = T_BISHOP; break;
        case T_KNIGHT: base = T_KNIGHT; break;
        default:       base = T_QUEEN; break;
    }
    return white ? base : (base | COLOR_BIT);
}

void makeMove(Board& b, const Move& m) {
    bool white = b.whiteToMove;
    int piece = b.sq[m.from];

    b.ep = -1;  // reset; set again only on a double push

    // Move the piece.
    b.sq[m.from] = EMPTY;

    if (m.flag == FLAG_EP) {
        // Captured pawn sits behind the destination square.
        int capSq = m.to + (white ? S_OFF : N_OFF);
        b.sq[capSq] = EMPTY;
        b.sq[m.to] = piece;
    } else if (m.flag == FLAG_CASTLE) {
        b.sq[m.to] = piece;
        // Move the rook.
        if (m.to == sqFromFR(6, white ? 0 : 7)) {        // king-side
            int rfrom = sqFromFR(7, white ? 0 : 7);
            int rto = sqFromFR(5, white ? 0 : 7);
            b.sq[rto] = b.sq[rfrom];
            b.sq[rfrom] = EMPTY;
        } else {                                          // queen-side
            int rfrom = sqFromFR(0, white ? 0 : 7);
            int rto = sqFromFR(3, white ? 0 : 7);
            b.sq[rto] = b.sq[rfrom];
            b.sq[rfrom] = EMPTY;
        }
    } else if (m.promo != 0) {
        b.sq[m.to] = promoPiece(m.promo, white);
    } else {
        b.sq[m.to] = piece;
        if (m.flag == FLAG_DOUBLE)
            b.ep = m.from + (white ? N_OFF : S_OFF);
    }

    // Update castling rights: any move from/to a rook square or a king move
    // clears the corresponding rights.
    auto clearBySquare = [&](int s) {
        if (s == sqFromFR(4, 0)) b.castling &= ~(CR_WK | CR_WQ);  // white king
        if (s == sqFromFR(4, 7)) b.castling &= ~(CR_BK | CR_BQ);  // black king
        if (s == sqFromFR(7, 0)) b.castling &= ~CR_WK;
        if (s == sqFromFR(0, 0)) b.castling &= ~CR_WQ;
        if (s == sqFromFR(7, 7)) b.castling &= ~CR_BK;
        if (s == sqFromFR(0, 7)) b.castling &= ~CR_BQ;
    };
    clearBySquare(m.from);
    clearBySquare(m.to);

    b.whiteToMove = !white;
}

// Generate fully legal moves by filtering pseudo-legal ones.
void genLegal(const Board& b, std::vector<Move>& out) {
    std::vector<Move> pseudo;
    genPseudoLegal(b, pseudo);
    out.clear();
    bool white = b.whiteToMove;
    for (const Move& m : pseudo) {
        Board nb = b;
        makeMove(nb, m);
        // After makeMove, side to move flipped; the mover's king must be safe.
        if (!inCheck(nb, white))
            out.push_back(m);
    }
}

// ---------------------------------------------------------------------------
// Perft
// ---------------------------------------------------------------------------

uint64_t perft(const Board& b, int depth) {
    if (depth == 0) return 1;
    std::vector<Move> moves;
    genLegal(b, moves);
    if (depth == 1) return moves.size();
    uint64_t nodes = 0;
    for (const Move& m : moves) {
        Board nb = b;
        makeMove(nb, m);
        nodes += perft(nb, depth - 1);
    }
    return nodes;
}

// ---------------------------------------------------------------------------
// Move <-> UCI string
// ---------------------------------------------------------------------------

std::string sqName(int sq) {
    std::string s;
    s += char('a' + fileOf(sq));
    s += char('1' + rankOf(sq));
    return s;
}

char promoChar(int type) {
    switch (type) {
        case T_QUEEN:  return 'q';
        case T_ROOK:   return 'r';
        case T_BISHOP: return 'b';
        case T_KNIGHT: return 'n';
        default:       return '\0';
    }
}

std::string moveToUci(const Move& m) {
    std::string s = sqName(m.from) + sqName(m.to);
    if (m.promo != 0) s += promoChar(m.promo);
    return s;
}

// Find the legal move matching a UCI string; returns true and fills `out`.
bool findMoveByUci(const Board& b, const std::string& uci, Move& out) {
    std::vector<Move> moves;
    genLegal(b, moves);
    for (const Move& m : moves) {
        if (moveToUci(m) == uci) { out = m; return true; }
    }
    return false;
}

// ---------------------------------------------------------------------------
// UCI loop
// ---------------------------------------------------------------------------

const char* START_FEN =
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

void applyMoves(Board& b, std::istringstream& iss) {
    std::string mv;
    while (iss >> mv) {
        Move m;
        if (findMoveByUci(b, mv, m))
            makeMove(b, m);
        // Unknown/illegal moves are ignored (should not happen with the harness).
    }
}

void handlePosition(const std::string& line, Board& b) {
    std::istringstream iss(line);
    std::string token;
    iss >> token;  // "position"
    iss >> token;  // "startpos" or "fen"

    if (token == "startpos") {
        parseFen(START_FEN, b);
        std::string next;
        if (iss >> next && next == "moves")
            applyMoves(b, iss);
    } else if (token == "fen") {
        // Read the six FEN fields.
        std::string fen, field;
        for (int i = 0; i < 6 && (iss >> field); i++) {
            if (field == "moves") break;  // defensive; shouldn't happen mid-FEN
            if (!fen.empty()) fen += " ";
            fen += field;
        }
        if (!parseFen(fen, b)) parseFen(START_FEN, b);
        std::string next;
        if (iss >> next && next == "moves")
            applyMoves(b, iss);
    }
}

// Pick the first legal move in sorted UCI-string order.
std::string pickBestMove(const Board& b) {
    std::vector<Move> moves;
    genLegal(b, moves);
    if (moves.empty()) return "0000";
    std::string best;
    for (const Move& m : moves) {
        std::string u = moveToUci(m);
        if (best.empty() || u < best) best = u;
    }
    return best;
}

}  // namespace

int main() {
    std::ios::sync_with_stdio(false);
    Board board;
    parseFen(START_FEN, board);

    std::string line;
    while (std::getline(std::cin, line)) {
        // Trim trailing carriage returns.
        while (!line.empty() && (line.back() == '\r' || line.back() == '\n'))
            line.pop_back();

        std::istringstream iss(line);
        std::string cmd;
        iss >> cmd;

        if (cmd == "uci") {
            std::cout << "id name MinimalCppEngine\n";
            std::cout << "id author Example\n";
            std::cout << "uciok\n";
            std::cout.flush();
        } else if (cmd == "isready") {
            std::cout << "readyok\n";
            std::cout.flush();
        } else if (cmd == "ucinewgame") {
            parseFen(START_FEN, board);
        } else if (cmd == "position") {
            handlePosition(line, board);
        } else if (cmd == "go") {
            std::string sub;
            iss >> sub;
            if (sub == "perft") {
                int depth = 0;
                iss >> depth;
                uint64_t nodes = perft(board, depth);
                std::cout << "info string perft " << nodes << "\n";
                std::cout.flush();
            } else {
                // Any normal search: report a legal move quickly.
                std::cout << "bestmove " << pickBestMove(board) << "\n";
                std::cout.flush();
            }
        } else if (cmd == "quit") {
            break;
        }
        // Unknown commands are ignored.
    }
    return 0;
}
