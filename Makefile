.PHONY: install test gate round doctor serve clean

VENV=.venv
PY=$(VENV)/bin/python

install:
	python3 -m venv $(VENV)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,server]"

test:
	$(PY) -m pytest -q

doctor:
	$(VENV)/bin/ceb doctor

gate:
	$(VENV)/bin/ceb gate run --track A --workspace examples/submissions/minimal_uci_engine_python

round:
	$(VENV)/bin/ceb round run --track A --workspace examples/submissions/minimal_uci_engine_python --round 1 --quick

serve:
	$(VENV)/bin/ceb server start --host 127.0.0.1 --port 8000

clean:
	rm -rf .pytest_cache **/__pycache__ build dist *.egg-info
