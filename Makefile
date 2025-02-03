
.ONESHELL:

default: lab

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

backup:
	rsync -az --delete --progress --exclude '*.nc' --exclude '__pycache__' --exclude '.ipynb_checkpoints' --exclude '*.pyc' --exclude '*.gpkg' --exclude 'dep_ls_coastlines*.gpkg' --exclude '*.tif' --exclude '.DS_Store' --exclude '.venv' . /Users/sachin/Dropbox/Projects/dep-projects
	du -sh /Users/sachin/Dropbox/Projects/dep-projects

docker:
	docker build -t intertidal .
	
