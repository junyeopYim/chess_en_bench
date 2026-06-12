# 운영자 보안 가이드

chess_en_bench는 직접 작성하지 않은 코드를 실행한다. 제출된 엔진(과 그
`build.sh`)은 평가 대상인 LLM 에이전트가 생성한다. 모든 제출물을 신뢰할 수
없는 것으로 취급한다. 이 문서는 운영자 관점의 가이드다. 하네스를 어떻게 안전하게
실행하는지, 각 격리 모드가 무엇을 하는지를 다룬다. 정식 신뢰 모델 — 자산, 전체
집행 목록, v0.3의 명시적 비목표 — 은
[SECURITY_MODEL.md](SECURITY_MODEL.md)를 참고한다.

직접 작성하지 않은 모든 제출물에 권장되는 격리는 **엔진 감옥(engine jail)**
(`--engine-jail docker`)이며, 이는 신뢰할 수 없는 엔진만 격리한다. 레거시
`--sandbox docker`(하네스 전체를 컨테이너에)는 여전히 존재하지만 숨겨진 eval
팩을 지원하지 않는다. 아래를 참고한다.

## 위협 모델

제출된 엔진은 임의의 네이티브 또는 인터프리터 프로그램이다. 적대적이거나 단순히
버그가 있는 제출물은 다음을 시도할 수 있다:

- 셸 명령을 실행하거나 하네스 프로세스로 탈출,
- 평가를 막으려고 영원히 멈추거나 단일 읽기를 정체,
- 하네스 메모리를 고갈시키려고 stdout/stderr를 범람,
- 고아가 된 자식 프로세스를 남김,
- 벤치마크 내부, 상대 엔진, 결과, 또는 파일시스템을 읽거나 수정,
- 네트워크 사용(더 강한 엔진 다운로드, 온라인 엔진 질의, 데이터 탈취),
- CPU, 메모리, 또는 디스크 고갈.

처음 네 부류는 모든 실행에서 프로세스 수준에서 완화된다. 마지막 세 부류는
신뢰할 수 없는 엔진을 `--engine-jail docker`로 실행할 때 격리된다. 기본값인
`--engine-jail none`(호스트 실행)에서는 이들이 정책 전용으로 남는다
(`specs/forbidden_behaviors.md`).

## 프로세스 수준에서 집행 (모든 실행)

모든 엔진 프로세스 처리는 `bench/ceb/uci/client.py`
(`UCIClient`)를 거친다. 그 파일에서 검증 가능한 구체적 보장:

- **argv 전용 생성, 결코 셸이 아님.** `command`가 문자열이면
  `UCIClient(command)`는 `TypeError`를 발생시킨다. 프로세스는
  `subprocess.Popen(argv_list)`로 시작하며 어디에도 `shell=True`가 없다.
- **모든 읽기에 타임아웃이 있다.** `read_line`, `expect`, `handshake`, `sync`,
  `go_movetime`, `go_perft`는 모두 데드라인을 받으며 영원히 블록하는 대신
  `EngineTimeout` / `EngineCrashed`를 발생시킨다.
- **제한된 stdout 수용.** 리더 스레드가 10,000 라인으로 상한된 큐
  (`_QUEUE_MAX_LINES`)에 공급하며, 각 라인은 8,192자로 절단된다
  (`_MAX_LINE_CHARS`). 범람하는 엔진은 자기 자신의 파이프에서 블록된다.
- **stderr는 폐기된다** (`stderr=subprocess.DEVNULL`).
- **프로세스 그룹 해체.** POSIX에서 엔진은 자체 세션에서 시작한다.
  `close()`는 `quit` → SIGTERM → SIGKILL을 전체 프로세스 그룹으로 단계적
  상승시킨다.
- **build.sh는 제한된 상태로 실행된다.** 게이트(`bench/ceb/gate/gate_runner.py`)는
  출력을 캡처하고 120초 타임아웃으로 그것을 호출한다.
  `--engine-jail none`에서는 호스트에서 `["bash", build.sh]`로 실행되고,
  `--engine-jail docker`에서는 감옥 안에서 실행된다(오프라인, 작업공간 쓰기
  가능).
- **모든 수가 오라클 검증된다** — `bench/ceb/chess/`에 대해 검증되며, 불법
  출력은 결함으로 기록되고 결코 맹목적으로 재생되지 않는다.
- **게이트 실패 세부 정보는 행 id만 인용한다** — bestmove/perft 검사 메시지에는
  FEN이 절대 포함되지 않으므로, 숨겨진 eval 팩 포지션이 리포트나 에이전트
  피드백을 통해 누출될 수 없다.

## 엔진 감옥 (`--engine-jail docker`) — 권장

이것은 공식 호스팅 평가가 사용하는 경로이며, 직접 작성하지 않은 모든 제출물에
사용할 경로다. 잠긴 컨테이너 안에 **신뢰할 수 없는 엔진만** 격리하고 평가기는
호스트에서 신뢰된 상태로 유지한다. 평가기는 호스트 측에서 숨겨진 팩을 읽고
감옥에 갇힌 엔진을 UCI로 구동하므로, `--engine-jail docker`는 `--eval-pack`과
**함께** 동작한다.

`ceb gate run`, `ceb round run`, `ceb track-b round run`은 모두
`--engine-jail none|docker`를 받는다(기본값 `none`). 이미지는 한 번 빌드한다
(`infra/docker/engine_jail.Dockerfile`, 태그 `chess-en-bench-jail:0.4`):

```sh
bash scripts/build_jail_image.sh
ceb gate run --track A --workspace runs/demo/workspace --engine-jail docker
ceb round run --track A --workspace runs/demo/workspace --round 1 \
    --engine-jail docker --eval-pack /path/to/private/pack
```

집행 (`bench/ceb/jail/docker_engine.py`):

- `--network none` — 외부 통신(egress) 전면 차단.
- `--read-only` rootfs 와 `--tmpfs /tmp` — 불변(immutable) 컨테이너 파일시스템.
- `--cpus 1 --memory 1g --pids-limit 128` — 리소스 상한 (`DEFAULT_LIMITS`).
- `--security-opt no-new-privileges`와 `--user <host-uid>:<host-gid>` —
  권한 상승 없음, 컨테이너 안에서 절대 root가 아님.
- 제출 작업공간이 `/submission`에 읽기 전용으로 마운트되는 **유일한** 마운트다
  (`-v <workspace>:/submission:ro`). 저장소 마운트도, eval 팩 마운트도, 상대
  엔진 마운트도 없다 — 엔진은 그 외에 아무것도 보지 못한다. 빌드 단계는
  작업공간을 쓰기 가능하게 마운트하지만(그래야 `./engine`을 생성할 수 있다)
  여전히 `--network none`을 유지한다.
- 감옥 이미지는 의도적으로 `ceb` 패키지를 설치하지 **않으므로**, 감옥 속 엔진은
  Python을 실행하더라도 평가기 코드를 임포트할 수 없다.
- 어디서나 argv 목록을 사용한다. 해석된 작업공간 경로에 `:` 또는 개행(`-v`
  필드 구분자)이 포함되면 거부되며, `/`를 포함하는 엔진 이름도 거부된다.
- Docker가 없거나 이미지가 없으면 조용한 호스트 폴백이 아니라 실행 가능한
  `EngineJailError`로 실패한다(Docker 설치 / `scripts/build_jail_image.sh`
  실행).

전체 자산 맵, 이미지 안에 `ceb`가 없다는 속성, 그리고 체크리스트→테스트 매핑은
[SECURITY_MODEL.md](SECURITY_MODEL.md)를 참고한다.

## 레거시 하네스 전체 샌드박스 (`--sandbox docker`)

`--sandbox docker`는 엔진 감옥보다 앞선다. 이는 전체 `ceb` 하네스를 하나의
컨테이너 안에서 다시 호출한다(`bench/ceb/sandbox/docker_runner.py`, 이미지
`chess-en-bench-evaluator:0.2`). 여전히 `--network none`,
`--read-only` + `--tmpfs /tmp`, `--cpus 2 --memory 2g --pids-limit 256`,
`--security-opt no-new-privileges`, non-root `--user`, 동일한 `:`/개행
마운트 경로 검증, 그리고 `CEB_INSIDE_SANDBOX=1` 재귀 가드를 적용한다. 저장소는
`/bench`에 읽기 전용으로 마운트되며, `runs/`와 작업공간만 쓰기 가능하다.

엔진 감옥을 선호한다. 레거시 샌드박스는 **`--eval-pack`을 거부하므로**(CLI가 그
조합에서 오류를 낸다) 숨겨진 팩 평가를 실행할 수 없다 — 그런 평가는 호스트에서
실행될 것이다. 공식 호스팅 평가는 `--sandbox docker`가 아니라 `--engine-jail
docker`를 사용한다.

## 집행되지 않음

- **호스트 실행이 여전히 기본값이다.** `--engine-jail none`(과 `--sandbox
  none`)은 제출물을 당신 사용자의 평범한 자식 프로세스로 실행한다 —
  파일시스템, 네트워크, 또는 리소스 격리가 없다. 그 무엇도 `--engine-jail
  docker`를 전달하도록 강제하지 않는다.
- **Docker 기본값을 넘는 seccomp/AppArmor 프로파일이 없고**, 사용자
  네임스페이스 리매핑도 없다.
- **엔진 stdin 쓰기는 무제한이다.** `UCIClient.send()`에는 타임아웃이 없다.
  stdin을 결코 비우지 않는 엔진은 가득 찬 파이프에서 하네스 쓰기를 블록할 수
  있다(읽기는 데드라인으로 보호되지만 쓰기는 그렇지 않다).
- **쓰기 가능한 경로(감옥 빌드의 `/submission`, `runs/`, 호스팅된 오브젝트
  스토어)에 디스크 쿼터가 없다.**

전체 비목표 목록(단일 노드 호스팅 백엔드, 결함을 접어 넣는 fastchess, 진단용
Track B CLI 실행)은 [SECURITY_MODEL.md](SECURITY_MODEL.md)를 참고한다. 결과
서명은 Ed25519 공개키(권장) 또는 레거시 HMAC을 사용한다 —
[RESULT_SIGNING.md](RESULT_SIGNING.md) 참고.

## 운영자 지침

- **직접 작성하지 않은 모든 제출물에는 `--engine-jail docker`를 사용한다.**
  먼저 감옥 이미지를 빌드한다. 신뢰된 로컬 디버깅에는 `--engine-jail none`을
  유지한다. 비공개 팩 실행을 위해 `--eval-pack`과 조합된다.
- 호스트에서 실행해야 한다면, 자격 증명을 보유한 머신이 아니라 일회용 환경
  (버리는 VM이나 전용 저권한 사용자)을 사용한다.
- 하네스를 결코 root로 실행하지 않는다. 감옥도 당신의 uid:gid를 매핑하여
  컨테이너 안에서 root를 거부한다.
- 호스트 모드(`--engine-jail none`) `ceb gate run` 전에 `build.sh`와 작업공간을
  훑어본다. 거기서는 당신의 권한으로 실행된다.
- 의심스러운 실행 후에는 환경을 정리하기보다 폐기한다.
- `runs/`와 `artifacts/`를 코드가 아니라 데이터로 취급한다.
- 제출물에 대한 정책 수준 규칙(네트워크 금지, 하네스 내부 읽기 금지 등)과 그
  결과는 `specs/forbidden_behaviors.md`에 규범적으로 명시되어 있다.
