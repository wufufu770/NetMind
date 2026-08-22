import os, tempfile

_tmp=tempfile.mkdtemp(prefix='netmind-tests-')
os.environ['NETMIND_DATA_FILE']=os.path.join(_tmp, 'store.json')
