PYTHON = python
SETUP = $(PYTHON) setup.py
PYDOCTOR ?= pydoctor
TESTRUNNER = $(shell which nosetests)

all: build 

doc:: pydoctor

pydoctor::
	$(PYDOCTOR) --make-html -c dulwich.cfg

build::
	$(SETUP) build
	$(SETUP) build_ext -i

install::
	$(SETUP) install

check:: build
	PYTHONPATH=. $(PYTHON) $(TESTRUNNER) dulwich

check-noextensions:: clean
	PYTHONPATH=. $(PYTHON) $(TESTRUNNER) dulwich

clean::
	$(SETUP) clean --all
	rm -f dulwich/*.so

coverage:: build
	PYTHONPATH=. $(PYTHON) $(TESTRUNNER) --cover-package=dulwich --with-coverage --cover-erase --cover-inclusive dulwich
