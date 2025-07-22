#!/bin/bash

DIR=$(dirname $0)

: ${GH:=gh}
: ${RELEASE_TAG:=$(date +"%Y-%m-%d")}

BRANCH=$(cd ${DIR} && git branch --show-current)

if $(${GH} release list | egrep -q "\s${RELEASE_TAG}\s"); then
    echo "A release with tag ${RELEASE_TAG} already exists."
    echo
    echo "To make a new release, create a new tag first."
    exit 1
fi

${GH} release create --target="${BRANCH}" "${RELEASE_TAG}" "${DIR}/commits.db"
