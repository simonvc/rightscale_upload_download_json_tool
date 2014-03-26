rightscale_upload_download_json_tool
====================================

[Abandonware] A python tool for downloading a RightScale deployment as a single JSON doc, and the ability to re-upload it.


http://devopsreactions.tumblr.com/post/68966751831/showcasing-your-cool-new-feature

A simple wrapper around rightscale deployments that can:

* Describe our most commonly used rightscale functionality in a JSON file and upload it to rightscale.

To run this:

Install virtualenv.

git clone this repo.
 
in the checkout, 

$ virtualenv .
$ ./bin/activate
$ pip install -r requirements.txt


Create a credentials file like simonvc.json:

{
  "email": "simon.vans-colina@simon.vc",
  "password": "yourpassword",
  "account": "12345"
}


usage: deploymentadmin.py [-h] -i USER_CREDENTIALS [-e EXPORT] [-m MASK]
                          [-o OUTPUT] [-l [LIST]] [-c [CLOUDS]] [-u UPLOAD]
                          [-a] [-t] [-v] [--links-debug] [--drop-inputs]
                          [--dry-run] [--tests]

RightScale Deployment Admin tool

optional arguments:
  -h, --help            show this help message and exit
  -i USER_CREDENTIALS, --user-credentials USER_CREDENTIALS
                        RightScale Identity Credentials in JSON format
  -e EXPORT, --export EXPORT
                        The name or URL of a deployment to export
  -m MASK, --mask MASK  Mask to condense the output from rightscale
  -o OUTPUT, --output OUTPUT
                        Output file for export
  -l [LIST], --list [LIST]
                        List RightScale deployments. Provide a substing to
                        search on, or leave blank for the full list.
  -c [CLOUDS], --clouds [CLOUDS]
                        List Clouds. Provide a substing to search on, or leave
                        blank for the full list.
  -u UPLOAD, --upload UPLOAD
                        Upload a rightscale deployment.
  -a, --apply-server-inputs
                        Just apply the server inputs to the next instances of
                        servers in a config file
  -t, --tag-deployment  Just apply the tags to servers in a config file
  -v, --verbose-debug   Show lookups as they happen
  --links-debug         Leave links intact when exporting
  --drop-inputs         Leave links intact when exporting
  --dry-run             Just show what would be done without contacting
                        RightScale
  --tests               run test cases

To list deployments use:
./deploymentadmin.py -i simonvc.json -list sandbox # to see a filtered list of all deployments containing sandbox
./deploymentadmin.py -i simonvc.json -list # to see an unfiltered list

To export a deployment use:
./deploymentadmin.py -i simonvc.json --export dev_aws_eu_wi_simonvc_sandbox --mask mask_for_import.json

To upload a deployment.json use:
./deploymentadmin.py -i simonvc.json -u dev_aws_eu_wi_simonvc_sandbox3.json
