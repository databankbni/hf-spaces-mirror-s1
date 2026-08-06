#!/bin/bash
git clone https://${GIT_TOKEN}@github.com/${GIT_USER}/${GIT_REPO}.git temp_code
if [ $? -eq 0 ]; then
    cp -r temp_code/. .
    rm -rf temp_code
else
    exit 1
fi

git clone -b database https://${GIT_TOKEN}@github.com/${GIT_USER}/${GIT_REPO}.git temp_data
if [ $? -eq 0 ]; then
    cp -r temp_data/. .
    rm -rf temp_data
fi

npm install --omit=dev
echo "============================================="
echo "DANH SÁCH FILE TRONG THƯ MỤC DATA:"
ls -lh data
echo "============================================="
npm start