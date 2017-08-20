#!/bin/bash

pip3 install --upgrade .
jupyter serverextension enable --py nbcull
jupyter-notebook --no-browser
