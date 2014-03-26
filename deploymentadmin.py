#!/usr/bin/env python

import sys
import json
import re
from copy import deepcopy
import argparse
import requests
from lxml import objectify

lookupRE=re.compile('@\((.*?)\)(.*)')

headers = {'X-API-VERSION': "1.5", 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/xml'}
json_headers = {'X-API-VERSION': "1.5", 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}

parser = argparse.ArgumentParser(description='RightScale Deployment Admin tool')
baseurl="https://us-3.rightscale.com"

parser.add_argument('-i', '--user-credentials', required=True, help='RightScale Identity Credentials in JSON format')
parser.add_argument('-e', '--export', help='The name or URL of a deployment to export')
parser.add_argument('-m', '--mask', help='Mask to condense the output from rightscale')
parser.add_argument('-o', '--output', help='Output file for export')

parser.add_argument('-l', '--list', nargs='?', const="blank_list", help='List RightScale deployments. Provide a substing to search on, or leave blank for the full list.')
parser.add_argument('-c', '--clouds', nargs='?', const="blank_list", help='List Clouds. Provide a substing to search on, or leave blank for the full list.')

parser.add_argument('-u', '--upload', help='Upload a rightscale deployment.')
parser.add_argument('-a', '--apply-server-inputs', action='store_true', default=False, help='Just apply the server inputs to the next instances of servers in a config file')
parser.add_argument('-t', '--tag-deployment', action='store_true', default=False, help='Just apply the tags to servers in a config file')

parser.add_argument('-v', '--verbose-debug', action='store_true', default=False, help='Show lookups as they happen') 
parser.add_argument('--links-debug', action='store_true', default=False, help='Leave links intact when exporting') 
parser.add_argument('--drop-inputs', action='store_true', default=False, help='Leave links intact when exporting') 
parser.add_argument('--dry-run', action='store_true', default=False, help='Just show what would be done without contacting RightScale')
parser.add_argument('--tests', action='store_true', default=False, help='run test cases')

def ppjson(j):
  return json.dumps(j, indent=2, sort_keys=True)

def RSGet(href, _filter=None):
  debug("RSGet %s" % href)
  headers = {'X-API-VERSION': "1.5", 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
  # filters come in {'field': 'selector'} format and get changed to {"filter[]": "field==selector"} format
  data=None
  if _filter:
    data=dict([('filter[]', '%s==%s' % (k, _filter[k])) for k in _filter])
    debug("building filter list: %s" % data)
  r=RS.get(baseurl+href, data=data, headers=headers)
  debug("RSGet got %s %s" % (r.status_code, r.text))
  if 200 <= r.status_code <= 210:
    json_from_rs=json.loads(r.text)
    return json_from_rs
  else:
    debug("Returning None because non 200 status code")
    return None

def get_cloud_from_export(djson):
  cloud="Autodetection failed. Suggest you try /api/clouds/2 here"
  try:
    cloud=djson['servers'][0]['next_instance']['cloud']
  except KeyError, e:
    debug("Failed to determine the cloud id automatically, is there a first server with a current instance in this deployment?")
  return cloud

def reverselookup(ahref):
  debug("REVERSE LOOKUP FOR: %s" % ahref)
  r=RS.get(baseurl+ahref, headers=json_headers)
  if 200 <= r.status_code <= 210:
    to_return=json.loads(r.text.encode('ascii', 'ignore'))
    if type(to_return) == type({}):
      return(to_return)
    else:
      return {}
  else:
    debug("Lookup failed")
    debug("%s %s" % (r.status_code, r.text) )
    return {}

def stringstartswith(thisstring, inthisstring):
  debug("STRING MATCH. Is %s in %s" % (thisstring, inthisstring))
  try:
    if inthisstring.encode('ascii', 'ignore').count(thisstring.encode("ascii", "ignore")):
      return inthisstring.startswith(thisstring)
    else:
      return False
  except:
    return False

def humanize_hrefs(adocument):
  if type([]) == type(adocument):
    return [humanize_hrefs(i) for i in adocument]
  elif type({}) == type(adocument):
    subdoc={}
    for key in adocument.keys():
      if stringstartswith("/api/", adocument[key]):
          target_href_dict = reverselookup(adocument[key])
          if target_href_dict.get('name'): subdoc.setdefault('name', target_href_dict.get('name'))
          if target_href_dict.get('revision'): subdoc.setdefault('revision', target_href_dict.get('revision'))
          if target_href_dict.get('id'): subdoc.setdefault('id', target_href_dict.get('id'))
      subdoc[key] = humanize_hrefs(adocument[key])
    return subdoc
  else:
    if stringstartswith('/api/', adocument): # oh for .startswith....
      debug ("found an href/api ref: %s" % adocument)
      if adocument.count('ssh_keys'):
        return reverselookup(adocument)['resource_uid']
      elif adocument.count('instance_type'):
        return reverselookup(adocument)['resource_uid']
      elif stringstartswith('/api/networks/', adocument):
        return (RSGet(adocument).get('name') or adocument)
      elif adocument.count('datacenters'):
        return (RSGet(adocument).get('name') or adocument)
      else:
        #return reverselookup(adocument) # left for now
        return adocument # left for now
    else:
      return adocument

def liftmask(d, m):
  to_return=json.loads('{}')
  if type(d) == type([]):
    return [liftmask(subd, m) for subd in d]
  for k in d.keys():
    if m.get(k) == 'include':
      to_return[k] = d[k]
    elif type(m.get(k)) == type({}):
      to_return[k] = liftmask(d.get(k), m.get(k)) 
    else:
      pass
  return to_return

def test_liftmask():
  print "TESTING liftmask"
  print "loading mask"
  mask=json.loads(""" { "n": "include", "i": "include", "h": "include", "nh": "include", "s": { "a": "include" } }""")
  print "loading testcase"
  testcase=json.loads(""" { "n": "a", "i": {"1": 2 }, "d": "error", "h": [{"a": "b"}, {"b": "c"} ], "s": { "a": "a", "b": "error" } } """)
  print "loading expected result"
  result=json.loads(""" { "n": "a", "i": {"1": 2 }, "h": [ {"a": "b"}, {"b": "c"} ], "s": { "a": "a" } }""")
  assert liftmask(testcase, mask) == result
  print "Test passed ok"



def rationalize_inputs(djson):
  #this is the before data strucutre
  # now for every input i want a dict
  # {input_name: {'value': 10} }
  servers_inputs = {}
  inputs_values_counts = {}
  for server in djson['servers']:
    servers_inputs[server['name']] = {}
    for _input in server['next_instance']['inputs']:
      servers_inputs[server['name']][_input['name']] = _input['value']
      inputs_values_counts.setdefault(_input['name'], {})
      inputs_values_counts[_input['name']].setdefault(_input['value'], 0)
      inputs_values_counts[_input['name']][_input['value']] += 1

  sa_inputs = {}
  for sa in djson['server_arrays']:
    sa_inputs[sa['name']] = {}
    for _input in sa['next_instance']['inputs']:
      sa_inputs[sa['name']][_input['name']] = _input['value']
      inputs_values_counts.setdefault(_input['name'], {})
      inputs_values_counts[_input['name']].setdefault(_input['value'], 0)
      inputs_values_counts[_input['name']][_input['value']] += 1

  # max(inputs_values_counts['PILTG_REGISTRARURL'].iterkeys(), key=lambda k: inputs_values_counts['PILTG_REGISTRARURL'][k])
  default_deployment_inputs=[]
  for input_key in inputs_values_counts:
    most_popular_value=max(inputs_values_counts[input_key], key=lambda k: inputs_values_counts[input_key][k])
    # turn back to horrible rightscale format
    default_deployment_inputs.append( {'name': input_key, 'value': most_popular_value} )


  # now re-write the deployment inputs with the most common inputs
  djson['inputs'] = djson['inputs'] + default_deployment_inputs

  # the servers inputs are now just the ones that arent in the default list
  for server in djson['servers']:
    if server.get('current_instance'):
      server['current_instance']['inputs'] = [_input for _input in server['next_instance']['inputs'] if _input not in default_deployment_inputs]
    if server.get('next_instance'):
      server['next_instance']['inputs'] = [_input for _input in server['next_instance']['inputs'] if _input not in default_deployment_inputs]
  for server_array in djson['server_arrays']:
    if server_array.get('current_instance'):
      server_array['current_instance']['inputs'] = [_input for _input in server_array['next_instance']['inputs'] if _input not in default_deployment_inputs]
    if server_array.get('next_instance'):
      server_array['next_instance']['inputs'] = [_input for _input in server_array['next_instance']['inputs'] if _input not in default_deployment_inputs]

 # convert these back to non rightscale format 
  djson['inputs'] = dict([(i['name'], i['value']) for i in djson['inputs']])
  for server in djson['servers']:
    server['next_instance']['inputs'] = dict([(i['name'], i['value']) for i in server['next_instance']['inputs']])
  for sa in djson['server_arrays']:
    sa['next_instance']['inputs'] = dict([(i['name'], i['value']) for i in sa['next_instance']['inputs']])
  return djson

def test_rationalize_inputs():
  print "Testing rationalize function"
  tdjson=json.loads(""" 
{ "inputs": [ { "name": "deployment_input", "value": "deploymentvalue" }, { "name": "default_server_value", "value": "default from deployment" } ], "name": "testdeploy",
    "server_arrays": [
        { "name": "sa1", "next_instance": { "inputs": [ { "name": "deployment_input", "value": "deploymentvalue" }, { "name": "server_array_input", "value": "majority" } ] } }, 
        { "name": "sa2", "next_instance": { "inputs": [ { "name": "deployment_input", "value": "deploymentvalue" }, { "name": "server_array_input", "value": "majority" } ] } }, 
        { "name": "sa3", "next_instance": { "inputs": [ { "name": "deployment_input", "value": "deploymentvalue" }, { "name": "server_array_input", "value": "minority" } ] } }
    ],
    "servers": [
        { "name": "server1", "next_instance": { "inputs": [ { "name": "deployment_input", "value": "deploymentvalue" }, { "name": "server_input", "value": "majority" } ] } }, 
        { "name": "server2", "next_instance": { "inputs": [ { "name": "deployment_input", "value": "deploymentvalue" }, { "name": "server_input", "value": "majority" } ] } },
        { "name": "server3", "next_instance": { "inputs": [ { "name": "deployment_input", "value": "deploymentvalue" }, { "name": "server_input", "value": "minority" } ] } } ] }
        """)
  
  expectedjson=json.loads(""" 
{ "inputs": { "default_server_value": "default from deployment", "deployment_input": "deploymentvalue", "server_array_input": "majority", "server_input": "majority" }, "name": "testdeploy", "server_arrays": [ { "inputs": {}, "name": "sa1", "next_instance": { "inputs": [] } }, { "inputs": {}, "name": "sa2", "next_instance": { "inputs": [] } }, { "inputs": { "server_array_input": "minority" }, "name": "sa3", "next_instance": { "inputs": [ { "name": "server_array_input", "value": "minority" } ] } } ], "servers": [ { "inputs": {}, "name": "server1", "next_instance": { "inputs": [] } }, { "inputs": {}, "name": "server2", "next_instance": { "inputs": [] } }, { "inputs": { "server_input": "minority" }, "name": "server3", "next_instance": { "inputs": [ { "name": "server_input", "value": "minority" } ] } } ]
}
    """)
  if not expectedjson == rationalize_inputs(tdjson):
    print ppjson(expectedjson)
    exit(1)
  assert expectedjson == rationalize_inputs(tdjson)
  print "test passed"

def load_deployment_from_json(filename):
  try:
    deployment=json.loads(open(filename).read())
  except Exception, e:
    print "Could not load or parse the json deployment file: ", filename
    print e
    exit(1)
  return deployment

def create_deployment(deployment):
  data={}
  data['deployment[name]'] = deployment['name']
  data['deployment[description]'] = (deployment.get('description') or "Deployment created by the deployment tool")
  if args.dry_run:
    print "DRY_RUN: Will create a deployment: %s" % deployment['name']
    return None
  r=RS.post(baseurl+'/api/deployments', data=data, headers=headers)
  if not 200 <= r.status_code <= 210: # any 200 level code is fine
    print "Failed to create domain! %s %s" % (r.status_code, r.text)
    return None
  else:
    return lookup("@(deployments)%s" % deployment['name'])

def create_volume(volume):
  debug(volume)
  print "Creating Volume %s" % volume['name']
  if lookup("@(volumes)%s" % volume['name']):
    print "Volume already exists"
    return lookup("@(volumes)%s" % volume['name'])
  data                             ={}
  data['volume[name]']             =volume['name']
  data['volume[size]']             =volume['size'] #gigabytes
  if volume.has_key('iops'):
    data['volume[iops]']             =volume['iops'] #iops
  data['volume[datacenter_href]']  =lookup("@(datacenters)%s" % volume['datacenter']) #'/api/clouds/2/datacenters/342887S8S5SU6'
  print "VOLUMES:"
  print data
  if args.dry_run:
    print "DRY_RUN: Will create a volume: %s" % volume['name']
    return None
  r=RS.post(baseurl+'/api/clouds/2/volumes', headers=headers, data=data)
  print r.text
  return lookup("@(volumes)%s" % volume['name'])


def create_server(server):
  #if args.verbose_debug:
    #ppjson(server)
  print "Creating Server", server['name']
  if lookup("@(servers)%s" % server['name']):
    print "Server already exists."
    return lookup("@(servers)%s" % server['name'])
  data={}
  data['server[name]']                              =server['name']
  #data['server[description]']                       =server['description']
  data['server[deployment_href]']                    =lookup("@(deployments)%s" % deployment['name'])
  data['server[instance][cloud_href]']              =cloud_href
  data['server[instance][server_template_href]']    =lookup("@(server_templates)%s" % server['next_instance']['server_template']['name'],
      template_revision=server['next_instance']['server_template']['revision'])
  if server['next_instance']['self'].get('multi_cloud_image'):
    # if its an array, test for the existance of each mci until you find one that actually exists
    if type([]) == type(server['next_instance']['self'].get('multi_cloud_image')):
      mci_to_use=None
      for possible_mci in server['next_instance']['self'].get('multi_cloud_image'):
        #does it exist
        r= RS.get(baseurl+possible_mci, headers=json_headers)
        if 200 <= r.status_code <= 210:
          mci_to_use = possible_mci
      if not mci_to_use:
        stderr("Failed to find an MultiCloud image that exists from the list i was given %s %s" % (r.status_code, r.text))
        exit(1)
    else:
      mci_to_use = server['next_instance']['self'].get('multi_cloud_image')
    data['server[instance][multi_cloud_image_href]'] = mci_to_use
  if server['next_instance']['self'].get('ssh_key'):
    data['server[instance][ssh_key_href]']            =lookup("@(ssh_keys)%s" % server['next_instance']['self']['ssh_key'])
  else:
    debug("Warning, no SSH key specified. Is this intentional or is this a datapipe server?")
  data['server[instance][instance_type_href]']      =lookup("@(instance_types)%s" % server['next_instance']['self']['instance_type'])
  security_groups=[]
  for sg in server['next_instance']['self']['security_groups']:
    debug("lookup the href for %s " % sg['name'])
    security_groups.append( lookup("@(security_groups)%s" % sg['name'] ))
  data['server[instance][security_group_hrefs][]']  = security_groups
  
  if args.dry_run:
    print "DRY_RUN: Will create a server %s " % server['name']
    return None
  debug(ppjson(data))
  r=RS.post(baseurl+'/api/servers', data=data, headers=headers)
  #todo check for the status code to ensure server was created 
  if 200 <= r.status_code <= 210: # any 200 level code is fine
    debug("Status: %s, Text: %s" % ( r.status_code, r.text))
    return lookup("@(servers)%s" % server['name'])
  else:
    stderr("Failed to create a server. Exiting. %s %s" % (r.status_code, r.text))
    exit(1)


def create_server_array(sa):
  if lookup("@(server_arrays)%s" % sa['name']):
    print "Server Array already exists"
    return lookup("@(server_arrays)%s" % sa['name'])

  data={}
  print("Creating a server array: %s" % sa['name'])
  debug("Creating a server array: %s" % sa)
  data["server_array[name]"] = sa['name']
  data["server_array[array_type]"] = sa['array_type']
  #data["server_array[deployment_href]"] = [l for l in sa['links'] if l['rel'] == 'deployment'][0]['href'] # why rightscale why
  data["server_array[deployment_href]"] = sa['server_array[deployment_href]']
  data["server_array[elasticity_params][bounds][min_count]"] = sa['elasticity_params']['bounds']['min_count']
  data["server_array[elasticity_params][bounds][max_count]"] = sa['elasticity_params']['bounds']['max_count']
  data["server_array[elasticity_params][pacing][resize_up_by]"] = sa['elasticity_params']['pacing']['resize_up_by']
  data["server_array[elasticity_params][pacing][resize_down_by]"] = sa['elasticity_params']['pacing']['resize_down_by']
  data["server_array[elasticity_params][pacing][resize_calm_time]"] = sa['elasticity_params']['pacing']['resize_calm_time']
  data["server_array[elasticity_params][alert_specific_params][decision_threshold]"] = sa['elasticity_params']['alert_specific_params']['decision_threshold']
  data["server_array[instance]"] = []
  data["server_array[instance][cloud_href]"] = sa['cloud_href']
  #data["server_array[instance][cloud_href]"] = sa['next_instance']['self']['cloud']
  data["server_array[instance][ssh_key_href]"] = lookup("@(ssh_keys)%s" % sa['next_instance']['self']['ssh_key'])
  #data["server_array[instance][inputs][][name]" = "" todo: calculate the correct server inputs
  #data["server_array[instance][inputs][][value] = ""
  debug( ppjson(sa['next_instance']))
  data["server_array[instance][server_template_href]"] = lookup("@(server_templates)%s" % sa['next_instance']['server_template']['name'], 
      template_revision = sa['next_instance']['server_template']['revision'])
  data["server_array[state]"] = "disabled"
  debug( data)
  #
  if args.dry_run:
    print "DRY_RUN: Will create a server array"
  else:
    r=RS.post(baseurl+"/api/server_arrays", data=data, headers=headers)
    if 200 <= r.status_code <= 210: # any 200 level code is fine
      debug("Status: %s, Text: %s" % ( r.status_code, r.text[:15]))
      return lookup("@(server_arrays)%s" % sa['name'])
    else:
      stderr("Failed to create a server array. Exiting. %s %s" % (r.status_code, r.text))
      exit(1)

def stderr(s):
  sys.stderr.write(s)
  sys.stderr.write('\n')

def set_server_inputs(server):
  print("Set server inputs")
  for wi in ['current_instance', 'next_instance']:
    #instance_id=lookup("@(%s_id)%s" %(wi, server['name']))
    instance=lookup("@(%s)%s" %(wi, server['name']))
    debug('Instance %s' % instance)
    #cloud_id = deployment['cloud']
    #cloud_number=cloud_id.split('/')[-1]
    #debug('Cloud number: shouldnt contain / is %s' % cloud_number)
    set_input_url=baseurl+'%s/inputs/multi_update' % instance
    debug("The input URL is: %s" % set_input_url)
    _inputs=((server.get('%s' % wi)or {}).get('inputs') or {})
    debug("The list of inputs for %s is %s" % (wi, _inputs))
    for _input in _inputs:
      data={}
      debug("Setting Input: %s" % _input)
      data['inputs[][name]' ]= _input
      data['inputs[][value]' ]= _inputs[_input]
      #data=server['%s' % wi]['inputs']
      debug(ppjson(data))
      if args.dry_run:
        print "DRY_RUN: Set inputs on %s: %s" % (server['name'], _input)
      else:
        r=RS.put(set_input_url, headers=headers, data=data)
        if 200 <= r.status_code <= 210:
          debug('%s %s' % (r.status_code, r.text))
        else:
          debug('%s %s' % (r.status_code, r.text))
          exit(1)

def set_serverarray_inputs(sa):
  print("Set server array inputs")
  for wi in ['current_instance', 'next_instance']:
    instance_id=lookup("@(%s_id)%s" %(wi, sa['name']))
    cloud_number=cloud_id.split('/')[-1]
    set_input_url=baseurl+'/api/clouds/%s/instances/%s/inputs/multi_update'% ( 
        cloud_number, instance_id)
    debug(set_input_url)
    for _input in sa['%s' % wi]['inputs']:
      data={}
      debug("Setting Server Array Input: %s" % _input)
      data['inputs[][name]' ]= _input['name']
      data['inputs[][value]' ]= _input['value']
      debug(ppjson(data))
      if args.dry_run:
        print "DRY_RUN: Set inputs on %s: %s" % (sa['name'], _input)
      else:
        r=RS.put(set_input_url, headers=headers, data=data)
        debug('%s %s' % (r.status_code, r.text))



def set_deployment_inputs(this_deployment):
  print("Set deployment inputs")
  this_deployment_href=lookup("@(deployments)%s" % this_deployment['name'])
  for i in this_deployment['inputs']:
    data={}
    data["inputs[%s]" % i]=this_deployment['inputs'][i]
    debug(data)
    if args.dry_run:
      print "DRY_RUN: Set deployment inputs: %s" % data
    else:
      debug( "Setting Inputs for deployment %s" % data)
      r=RS.put(baseurl+'%s/inputs/multi_update' % this_deployment_href, headers=headers, data=data)
      debug("%s %s" % (r.status_code, r.text))
      if 200 <= r.status_code <= 210: # any 200 level code is fine
        debug("Success: Set %s" % i)
      else:
        print "Was unable to set deployment inputs. ABORT"
        print r.status_code, r.text
        exit(1)
      

def create_recurring_volume_attachment(volume):
  print "Creating Volume Attachment between %s and %s" % (volume['attached_to'], volume['name'])
  storage=lookup(lookup("@(volumes)%s" % volume['name']))
  runnable=promote_links(RSGet("/api/servers", _filter={"name": volume['attached_to']}))[0]
  debug(ppjson(runnable))
  runnables_cloud_id = runnable['next_instance'].split('/')[3]
  debug("This server is running in cloud %s, so the volume attachment will be there too." % runnables_cloud_id)
  if lookup("@(volume_attachment_pair)%s:%s:%s" % (storage, runnable['self'], runnables_cloud_id)):
    print("The recurring volume attachment already exists.")
    return True
  if not volume.get('device'):
    print "WARNING: %s has no device specified, assuming /dev/xvdj (which may be wrong)" % volume['name']
    #todo: fix this so that we also export the device.
    volume['device'] = '/dev/xvdj'
  data={}
  data['recurring_volume_attachment[device]'] = volume["device"]
  data['recurring_volume_attachment[storage_href]'] = storage
  data['recurring_volume_attachment[runnable_href]'] = runnable['self']
  if args.dry_run:
    print "DRY_RUN: Will create a volume attachment between %s and %s" %(storage, runnable['name'])
    return True
  else:
    r=RS.post(baseurl+'/api/clouds/%s/recurring_volume_attachments' % runnables_cloud_id, headers=headers, data=data)
    debug("Status: %s, Text: %s" % ( r.status_code, r.text))
    if 200 <= r.status_code <= 210: # any 200 level code is fine
      return True
    else:
      print "Failed to create a Recurring Volume Attachment"
      print "%s %s" % (r.status_code, r.text)
      return False

def debug(s):
  if args.verbose_debug:
    print s
  
def lookup(lookupstring, fail_if_not_found=False, **kwargs):
  def short_return(something, **kwargs):
    if not something and fail_if_not_found:
      raise NameError("%s not found" % v)
    if type([]) == type(something):
      if len(something) == 1:
        debug("Lookup: Searched %-30s Found %-50s" % (lookupstring, something))
        return something[0]
      else:
        debug("Lookup: Searched %-30s Found %-50s" % (lookupstring, something))
        return something
    else:
      debug("Lookup: Searched %-30s Found %-50s" % (lookupstring, something))
      return something

  if not lookupRE.match(lookupstring):
    debug("Lookup non lookupstring:  %s " % lookupstring)
    return lookupstring
  data={}
  k,v = lookupRE.search(lookupstring).groups()

  if k=="deployments":
    r=RS.get(baseurl+"/api/deployments", headers=headers, data=data).text.encode('ascii', 'ignore')
    return short_return(objectify.fromstring(r).xpath("//deployments/deployment[name = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=="ssh_keys":
    r=RS.get(baseurl+"/api/clouds/%s/ssh_keys" % cloud_id, headers=headers, data=data).text.encode('ascii', 'ignore')
    try:
      r=short_return( objectify.fromstring(r).xpath("//ssh_keys/ssh_key[resource_uid = '%s']/links/link[@rel = 'self']/@href" % v))
      return r
    except:
      r= promote_links(RSGet("/api/clouds/%s/ssh_keys" % cloud_id, _filter={"resource_uid": v}))[0]
      debug(r)
      return r['self']


  elif k=="datacenters":
    r=RS.get(baseurl+"/api/clouds/%s/datacenters" % cloud_id, headers=headers, data=data).text.encode('ascii', 'ignore')
    return short_return( objectify.fromstring(r).xpath("//datacenters/datacenter[resource_uid = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=='clouds':
   r=RS.get(baseurl+"/api/clouds", headers=headers, data=data).text.encode('ascii', 'ignore')
   return short_return( objectify.fromstring(r).xpath("//clouds/cloud[name = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=='cloud_id':
    return lookup("@(clouds)%s" % v).split('/')[-1] # just grab the ID from the end of the URL
  elif k=='server_templates':
    data={}
    data['filter[]'] = ["name==%s" % v, "revision==%s" % kwargs['template_revision']]
    r=RS.get(baseurl+"/api/server_templates", headers=headers, data=data).text.encode('ascii', 'ignore')
    return short_return( objectify.fromstring(r).xpath( "//server_templates/server_template/links/link[@rel = 'self']/@href" ))
  elif k=='security_groups':
    r=RS.get(baseurl+"/api/clouds/%s/security_groups" % cloud_id, headers=headers).text.encode('ascii', 'ignore')
    return short_return( objectify.fromstring(r).xpath("//security_groups/security_group[name = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=='instance_types':
    r=RS.get(baseurl+"/api/clouds/%s/instance_types" % cloud_id, headers=headers).text.encode('ascii', 'ignore')
    return short_return( objectify.fromstring(r).xpath("//instance_types/instance_type[name = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=='volume_attachment_pair':
    storage, runnable, runnables_cloud_id = v.split(":")
    debug("looking for a RVA between %s and %s in cloud %s" % (storage, runnable, runnables_cloud_id))
    r=promote_links(RSGet("/api/clouds/%s/recurring_volume_attachments" % runnables_cloud_id, _filter={"storage_href": storage}))
    return r
  elif k=='volumes':
    r=RS.get(baseurl+"/api/clouds/%s/volumes" % cloud_id, headers=headers).text.encode('ascii', 'ignore')
    return short_return( objectify.fromstring(r).xpath("//volumes/volume[name = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=='servers':
    r=RS.get(baseurl+"/api/servers/", headers=headers).text.encode('ascii', 'ignore')
    return short_return( objectify.fromstring(r).xpath("//servers/server[name = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=='server_arrays':
    r=RS.get(baseurl+"/api/server_arrays/", headers=headers).text.encode('ascii', 'ignore')
    return short_return( objectify.fromstring(r).xpath("//server_arrays/server_array[name = '%s']/links/link[@rel = 'self']/@href" % v))
  elif k=='next_instance':
    r=RS.get(baseurl+"/api/servers/", headers=headers).text.encode('ascii', 'ignore')
    next_instances=objectify.fromstring(r).xpath("//servers/server[name = '%s']/links/link[@rel = 'next_instance']/@href" % v)
    if type(next_instances) == type([]):
      debug("Found %s next instances" % len(next_instances))
    else:
      debug("Next Instance is: %s" % next_instances)
    return short_return(next_instances)
  elif k=='current_instance':
    r=RS.get(baseurl+"/api/servers/", headers=headers).text.encode('ascii', 'ignore')
    current_instances=objectify.fromstring(r).xpath("//servers/server[name = '%s']/links/link[@rel = 'current_instance']/@href" % v)
    if type(current_instances) == type([]):
      debug("Found %s current instances" % len(current_instances))
    else:
      debug("Next Instance is: %s" % current_instances)
    return short_return(current_instances)
  elif k=='next_instance_id':
    return lookup("@(next_instance)%s" % v).split('/')[-1] # just grab the ID from the end of the URL
  elif k=='current_instance_id':
    to_return=lookup("@(current_instance)%s" % v)# just grab the ID from the end of the URL
    if type([]) == type(to_return):
      debug("WARNING list detected for current instance")
      debug("to_return %s" % to_return)
    if to_return:
      return to_return.split('/')[-1] 
    else:
      return None
  elif k=='rva_attachment_pair':
    debug("looking up the recurring volume %s" % v)
    storage,runnable = v.split(":")
    data['filter[]'] = ["storage_href==%s" % storage, "runnable_href==%s" % runnable]
    r=RS.get(baseurl+'/api/clouds/%s/recurring_volume_attachments' % cloud_id, headers=headers, data=data).text.encode('ascii', 'ignore')
    rvas=objectify.fromstring(r).xpath("//recurring_volume_attachments/recurring_volume_attachment")
    debug("returning len rvas: %s" % len(rvas))
    return rvas
  else:
    print "Lookup: Does not  know how to handle %s" % k
    return None

def get_deployments(filterstring):
  data={}
  headers = {'X-API-VERSION': "1.5", 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
  r=RS.get(baseurl+'/api/deployments', headers=headers)
  if not 200 <= r.status_code <= 210:
    print "List of deployments resulted in: ",
    print  r.text,r.status_code
    exit(1)
  else:
    if filterstring == "blank_list":
      return json.loads(r.text.encode('ascii', 'ignore')) 
    else:
      stderr( "Filtering the deployment list on '%s'" % filterstring)
      return [d for d in json.loads(r.text.encode('ascii', 'ignore')) if filterstring in d['name']]

  return None

def get_clouds(filterstring):
  data={}
  headers = {'X-API-VERSION': "1.5", 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'}
  r=RS.get(baseurl+'/api/clouds', headers=headers)
  if not 200 <= r.status_code <= 210:
    print "List of clouds resulted in: ",
    print  r.text,r.status_code
    exit(1)
  else:
    if filterstring == "blank_list":
      return json.loads(r.text.encode('ascii', 'ignore')) 
    else:
      stderr( "Filtering the deployment list on '%s'" % filterstring)
      return [d for d in json.loads(r.text.encode('ascii', 'ignore')) if d['name'].count(filterstring) ]
      #return [d for d in json.loads(r.text.encode('ascii', 'ignore')) if filterstring in d['name'] or filterstring in d['description']]
  return None

def login_to_rightscale(credentialjson):
  try:
    credentials=json.loads(open(credentialjson).read())
  except Exception, e:
    f=open(credentialjson, "w")
    f.write('{ "account": "51401", "email": "first.last@pearson.com", "password": "yourpassword" }')
    print "Cound not load or parse %s" % credentialjson
    print "Please edit %s and enter your correct rightscale login credentails" % credentialjson 
    exit (1)
  debug( "Logging in with %s to account %s" % (credentials['email'], credentials['account']))
  credentials['account_href'] = '/api/accounts/%s' % credentials['account']
  RightSession=requests.Session()
  r=RightSession.post(baseurl+"/api/session", headers=headers, data=credentials)
  if not 200 <= r.status_code <= 210:
    print "Could not log in. Please check your credentials."
    print r.status_code, r.text
    exit(1)
  else:
    return RightSession


def get_deployment_tags(name):
  href=lookup("@(deployments)%s" % name)
  data={}
  data['resource_hrefs[]'] = [href]
  debug(data)
  r=RS.post(baseurl+'/api/tags/by_resource', data=data, headers=json_headers)
  debug(r.text)
  if not 200 <= r.status_code <= 210: # any 200 level code is fine
    print "Failed to get Tags %s %s" % (r.status_code, r.text)
    return None
  else:
    rsv= json.loads(r.text.encode('ascii', 'ignore'))
    first_returned = rsv[0]['tags'] # ok because we're only passing in a single href to get tags on
    try:
      normal_json=dict([(v['name'].split('=')[0], v['name'].split('=')[1]) for v in first_returned])# Rightscale doesnt understand JSON
    except IndexError, e:
      stderr("Unable to unpack the tags for this deployment, do they exist or are they in the wrong format?")
      debug("What is wrong with: %s" % first_returned)
      exit(1)
    return normal_json

def set_tags(resource, tags):
  data={}
  print "Tagging.. %s %s" % (resource, ",".join(t for t in tags))
  debug("Tag %s with the tags %s" %(resource, ",".join(tags)))
  data['resource_hrefs[]'] = resource
  data['tags[]'] = ["%s=%s" %(k,tags[k]) for k in tags.keys()]
  debug(data)
  if args.dry_run:
    print "DRY_RUN: Will tag %s with %s" % (resource, tags)
  else:
    r=RS.post(baseurl+'/api/tags/multi_add', headers=headers, data=data)
    debug("%s - %s" % (r.status_code, r.text))
  return None # return True if the status code is 201?

class Object(object):
  pass

class DryRunner:
  def __init__(self, realRightScale):
    self.RS = realRightScale
  def get(self, url, *pargs, **kwargs):
    debug("Get request to %s" % url)
    debug( kwargs)
    if not kwargs.has_key('data'):
      kwargs['data'] = {}
    return self.RS.get(url, headers=kwargs['headers'], data=kwargs['data'])
  def post(self, url, *pargs, **kwargs):
    debug("POST request to %s" % url)
    debug( "URL: %s" % url)
    for kwarg in kwargs:
      debug( "POST: %s: %s" % (kwarg, kwargs[kwarg]))
    r=Object()
    r.status_code=201
    r.text=None
    return r
  def put(self, url, *pargs, **kwargs):
    debug("Put request to %s" % url)
    debug( "URL: %s" % url)
    for kwarg in kwargs:
      debug( "POST: %s: %s" % (kwarg, kwargs[kwarg]))
    r=Object()
    r.status_code=202
    r.text=None
    return r

def export_self(href, hint=None):
  drop_list = {
      'self': ['state', 'subnets', 'created_at', 'updated_at', 'private_ip_addresses', 'public_ip_addresses', 'resource_uid', 'pricing_type'],
      }
  debug('Export Self code here')
  data={}
  data['view']='extended'
  r=RS.get(baseurl+href, data=data, headers=json_headers)
  debug("status %s looks like %s" % (r.status_code, r.text[:25]))
  if 200 <= r.status_code <= 210:
    j=json.loads(r.text.encode('ascii', 'ignore'))
    for link in (j.get('links') or []):
      if link['rel'] not in (drop_list.get(hint) or []):
        j[link['rel']] = link['href']
      if j.get('links') and not args.links_debug: del j['links']
  else:
    j={}
    debug("returning a blank dictionary for %s" % href)
  return j

def export(name_or_href, hint="deployments"):
  drop_list = {
      'deployments': [],
      'server_template': ['description'] ,
      'servers': ['private_ip_addresses', 'public_ip_addresses', 'updated_at', 'created_at', 'updated_at'],
      'next_instance': ['created_at', 'updated_at', 'private_ip_addresses', 'public_ip_addresses', 'resource_uid', 'pricing_type'],
      'current_instance': ['created_at', 'updated_at', 'private_ip_addresses', 'public_ip_addresses', 'resource_uid', 'pricing_type'],
      }
  if args.drop_inputs:
    drop_list['deployments'].append('inputs')
    drop_list['servers'].append('inputs')
    drop_list['next_instance'].append('inputs')
    drop_list['current_instance'].append('inputs')

  links_to_follow=['servers', 
              'current_instance',
              'next_instance',
              'ipaddresses',
              'inputs',
              'volume_attachments',
              'server_template',
              'server_arrays',
              'resource',
              'clouds',
              'recurring_volume_attachments',
              'volumes']
  dont_follow_but_include=['cloud', 'server_template', 'multi_cloud_image']

  debug("In export with %s, %s" %(name_or_href, hint))

  if not name_or_href.count("/api/"):
    debug("Not an href, assuming a name. %s" % name_or_href)
    filterspec={'filter[]': ['name==%s' % name_or_href]}
    r=RS.get(baseurl+"/api/"+hint, data=filterspec, headers=json_headers)
    debug("Status: %s %s" % (r.status_code, r.text))
    rj=json.loads(r.text) 
    return export(get_self_href_from_links(rj))
  else:
    debug("api call to rightscale %s" % baseurl+name_or_href)
    r=RS.get(baseurl+name_or_href, headers=json_headers)
    debug("status %s looks like %s" % (r.status_code, r.text[:25]))
    if 200 <= r.status_code <= 210:
      j=json.loads(r.text.encode('ascii', 'ignore'))
    else:
      j={}
      debug("returning a blank dictionary for %s" % name_or_href)
      return j
    if j == []:
      debug("Returning a blank dictionary because %s was a blank list" % hint)
      return []
    if type(j) != type([]): # begin code to handle single dicts
      for link in (j.get('links') or []):
        if link['rel'] == 'self': # process self links because rightscale
          j[link['rel']] = export_self(link['href'], hint=link['rel'])
        if link['rel'] in dont_follow_but_include:
          j[link['rel']] = link['href']
          #todo: if the link is a self, then do an extended export on it.
        if link['rel'] in links_to_follow:
          # *** MAGIC RECURSIVE FUNCTION GOES HERE ****
          j[link['rel']] = export(link['href'], hint=link['rel'])
        if j.get('links') and not args.links_debug: del j['links']
        if j.get('actions') and not args.links_debug: del j['actions']
        for drop in (drop_list.get(hint) or []):
          if j.get(drop) and not args.links_debug:
            del j[drop]
      return j
    #end code to handle single dicts
    else: #begin code to handle lists
      return_list=[]
      for eachj in j:
        #debug("each j in j")
        # recursively enrich the document
        for link in (eachj.get('links') or []):
          #ppjson( j['links'])
          if link['rel'] in links_to_follow:
            eachj[link['rel']] = export(link['href'], hint=link['rel'])
          if eachj.get('links') and not args.links_debug: del eachj['links']
          if eachj.get('actions') and not args.links_debug: del eachj['actions']
          for drop in (drop_list.get(hint) or []):
            if eachj.get(drop) and not args.links_debug: del eachj[drop]
        return_list.append( eachj)
        #debug('adding to returnlist')
        #debug(len(return_list))
      return return_list
    #end code to handle lists

#todo Hacky code to get things not directly accessible from the deployment tree go here.
def find_volumes_attached_to(href, cloud_id=2):
  data={}
  data['filter[]']='instance_href==%s' % href
  r=RS.get(baseurl+'/api/clouds/%s/volume_attachments' % cloud_id, headers=json_headers, data=data)
  debug("%s %s" % (r.status_code, r.text))
  return json.loads(r.text)

def promote_links(j):
  def _pl(j):
    for d in j['links']:
      key = d['rel']
      value = d['href']
      j.setdefault(key, value)
    del j['links']
    return j
  if type([]) == type(j):
    return [_pl(element) for element in j]
  else:
    return _pl(j)

def get_volumes_for_servers_in(djson):
  volumes_to_return=[]
  for server in djson['servers']:
    debug('Finding the volumes associated with the server %s' % server['name'])
    if server.get('current_instance'):
      volume_attachments_list=RSGet(server['current_instance']['self']['volume_attachments'])
      volume_attachments_list=promote_links(volume_attachments_list)
      for volume_attachment in volume_attachments_list:
        single_volume=RSGet(volume_attachment['volume'])
        single_volume=promote_links(single_volume)
        single_volume['attached_to'] = server['name']
        single_volume['device'] = volume_attachment['device']
        volumes_to_return.append(single_volume)
  debug("This deployment requires the following volumes:")
  debug(ppjson(volumes_to_return))
  return volumes_to_return

def get_ip_addresses_for_servers_in(djson):
  eips=[]
  for server in djson['servers']:
    if not server.get('current_instance'):
      stderr("Warning: No current instance found for %s, elastic ip addresses will not be exported for this server" % server['name'])
      continue
    cloud_id=server['current_instance']['cloud']
    debug("looking for IP addresses associated with %s" % server['current_instance']['self']['self'])
    ipaddress_bindings=RSGet('%s/ip_address_bindings' % cloud_id, _filter={"instance_href": server['current_instance']['self']['self']})
    ipaddress_bindings=promote_links(ipaddress_bindings)
    for ipaddress_binding in ipaddress_bindings:
      ipaddress=RSGet(ipaddress_binding['ip_address'])
      ipaddress=promote_links(ipaddress)
      ipaddress['attached_to'] = server['name']
      eips.append(ipaddress)
  return eips

def get_self_href_from_links(j):
  print debug("Get the self href from the lisks of the first j")
  if j:
    rval= [link['href'] for link in j[0]['links'] if link['rel'] == 'self'][0]
    debug("self href is: %s " % rval)
    return rval
  else:
    print "Are you sure the deployment you specified actually exists?"
    print "This might be a bug, but i can't tell from here"
    raise Exception
     

if '__main__' in __name__: 

  args=parser.parse_args()
  debug(args)

  debug("Attempting to login with %s" % args.user_credentials)
  RS=login_to_rightscale(args.user_credentials)
  if args.dry_run:
    RS=DryRunner(RS)

  if args.clouds:
    for d in get_clouds(args.clouds):
      print "%-50s %-8s %-50s" % (d['name'], lookup("@(cloud_id)%s" % d['name']), d['description'])

  if args.list:
    for d in get_deployments(args.list):
      if args.verbose_debug:
        print "%-50s %-50s" % (d['name'], d['description'])
      else:
        print d['name']

  if args.apply_server_inputs:
    for server in deployment['servers']:
      if server.has_key('inputs'):
        set_server_inputs(server)

  if args.tag_deployment:
    for server in deployment['servers']:
      server_href = lookup("@(servers)%s" % server['name'])
      debug(server_href)
      tag(server_href, deployment['tags'])
      
  if args.export:
    debug( "Exporting config from %s "% args.export)
    exported=export(args.export)
    stderr("This is an export of %s" % exported['name'])
    exported["tags"]=get_deployment_tags(exported['name'])
    debug("Before rationalizing %s" % len(json.dumps(exported)))
    # determine the cloud to store at the deployment level from where the current servers are
    exported['cloud'] = get_cloud_from_export(exported)
    exported=rationalize_inputs(exported) # compress inputs back into the deployment where possible
    exported['volumes'] = get_volumes_for_servers_in(exported)
    exported['ip_addresses'] = get_ip_addresses_for_servers_in(exported)
    exported=humanize_hrefs(exported) # convert the hrefs back to names where they're found
    exported['cloud'] = RSGet(exported['cloud'])['name'] # when were done with it.
    debug("After rationalizing %s" % len(json.dumps(exported)))

    if args.mask:
      mymask=json.loads(open(args.mask).read())
      final_output=ppjson(liftmask(exported, mymask))
    else:
      final_output=ppjson(exported)
    if args.output:
      open(args.output, 'w').write(final_output)
    print final_output

  if args.tests:
    test_liftmask()
    test_rationalize_inputs()
    exit(0)

  if args.upload:
    deployment=load_deployment_from_json(args.upload)
    # cloud = 'eu west' cloud_id=2 cloud_href=/api/clouds/2 
    cloud=deployment.get('cloud')
    cloud_object = promote_links(RSGet('/api/clouds', _filter={'name': cloud}))[0]
    cloud_href=cloud_object['self']
    cloud_id = cloud_href.split('/')[-1] #its the last part
    for server in deployment.get('servers'):
      server['cloud'] = cloud
      server['cloud_id'] = cloud_id
      server['cloud_href'] = cloud_href
    for server_array in deployment.get('server_arrays'):
      server_array['cloud'] = cloud
      server_array['cloud_id'] = cloud_id
      server_array['cloud_href'] = cloud_href
    required_tags='pearsonbilling:environment pearsonbilling:platform'.split(' ')
    debug ( ppjson ( deployment.get('tags')))
    if not deployment['tags']:
      print "The deployment JSON does not have a tags section. Refusing to continue."
      exit(1)
  
    missing_tags=[tag for tag in required_tags if not (deployment.get('tags') or {}).get(tag)]
    if missing_tags:
      print "The following tags are missing. Please add them to your deployment json and try again"
      print " ".join(missing_tags)
      exit(1)

    if not lookup("@(deployments)%s" % deployment['name']):
      print "Deployment does not exist, creating."
      create_deployment(deployment)
    else:
      print "Deployment %s already exists" % deployment['name']
    # tag deployment

    set_tags(lookup("@(deployments)%s" % deployment['name']), deployment.get('tags'))

    #todo: actually add the tags to the deployment

    set_deployment_inputs(deployment)

    for volume in (deployment.get('volumes') or []):
      create_volume(volume)
      set_tags(lookup("@(volumes)%s" % volume['name']), deployment.get('tags'))

    for server in (deployment.get('servers') or []):
      create_server(server)
      server_href = lookup("@(servers)%s" % server['name'])
      set_server_inputs(server)
      set_tags(server_href, deployment['tags'])

    for sa in (deployment.get('server_arrays') or []):
      sa['server_array[deployment_href]'] = lookup("@(deployments)%s" % deployment['name'])
      sa['server_array[instance][cloud_href]'] = deployment['cloud']
      create_server_array(sa)
      server_array_href = lookup("@(server_arrays)%s" % sa['name'])
      if sa.has_key('inputs'):
        set_server_array_inputs(server)
      set_tags(server_array_href, deployment['tags'])

    for volume in (deployment.get('volumes') or []):
      create_recurring_volume_attachment(volume)

    for ipaddress in (deployment.get('ip_addresses') or []):
      print "Not creating an Elastic IP address. Please do this manually if needed"
      print ppjson(ipaddress)

