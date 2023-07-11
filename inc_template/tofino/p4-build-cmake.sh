#!/bin/bash

echo $PWD/$1
mkdir $PWD/build && cd $PWD/build
cmake $SDE/p4studio/ \
-DCMAKE_INSTALL_PREFIX=$SDE/install \
-DCMAKE_MODULE_PATH=$SDE/cmake \
-DP4_NAME=$1 \
-DP4_PATH=$PWD/$1.p4
make $1