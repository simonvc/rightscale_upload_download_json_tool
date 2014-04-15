FROM ubuntu

MAINTAINER simon.vans-colina@pearson.com

RUN apt-get -y install python-setuptools git-core build-essential
RUN apt-get -y install python-dev
RUN easy_install pip
RUN apt-get -y install libxml2-dev libxslt1-dev python-dev
ADD . /software
RUN pip install -r /software/requirements.txt

WORKDIR /software
ENTRYPOINT ["python", "deploymentadmin.py"]
