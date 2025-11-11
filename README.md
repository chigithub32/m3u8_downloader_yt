sudo apt update

sudo apt install -y git python3 python3-venv python3-pip ffmpeg

cd ~

git clone https://github.com/chigithub32/m3u8_downloader_yt.git

cd m3u8_downloader_yt

python3 -m venv venv

. venv/bin/activate

pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --upgrade pip

pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

python run.py

浏览器访问 主机ip:5001

docker安装：apt install git

cd ~

git clone https://github.com/chigithub32/m3u8_downloader_yt.git

cd m3u8_downloader_yt

docker build -t m3u8-downloader .

docker run -d -p 5001:5001 \
  --privileged \
  -v /mnt/:/downloads \
  m3u8-downloader:latest

