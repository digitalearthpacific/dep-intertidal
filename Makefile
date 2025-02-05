
.ONESHELL:

default: test

lab:
	BROWSER=firefox uv run --with jupyter jupyter-lab

upgrade:
	uv pip list --outdated
	rm uv.lock
	uv sync #--prerelease=allow
	uv lock --upgrade
	#uv pip install -e tools

env:
	. .venv/bin/activate

docker:
	docker build -t intertidal .
	
test:
	uv run src/run.py --tile-id 77,19 --year 2024 --version 0.0.1

fmt:
	black src/
