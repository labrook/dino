import sys
import os
import yaml
import redis


dino_env = sys.argv[1]
dino_home = sys.argv[2]

if dino_home is None:
    raise RuntimeError('need environment variable DINO_HOME')
if dino_env is None:
    raise RuntimeError('need environment variable DINO_ENVIRONMENT')


def load_secrets_file(config_dict: dict) -> dict:
    from string import Template
    import ast

    secrets_path = dino_home + '/secrets/%s.yaml' % dino_env

    # first substitute environment variables, which holds precedence over the yaml config (if it exists)
    template = Template(str(config_dict))
    template = template.safe_substitute(os.environ)

    if os.path.isfile(secrets_path):
        try:
            secrets = yaml.safe_load(open(secrets_path))
        except Exception as e:
            raise RuntimeError("Failed to open secrets configuration {0}: {1}".format(secrets_path, str(e)))
        template = Template(template)
        template = template.safe_substitute(secrets)

    return ast.literal_eval(template)


config = yaml.safe_load(open(dino_home + '/dino.yaml'))[dino_env]
config = load_secrets_file(config)

dbtype = config['database']['type']

the_count = 0

if dbtype == 'rdbms':
    dbdriver = config['database']['driver']
    dbname = config['database']['db']
    dbhost = config['database']['host']
    dbport = config['database']['port']
    dbuser = config['database']['user']
    dbpass = config['database']['password']

    if dbdriver.startswith('postgres'):
        import psycopg2

        conn = psycopg2.connect("dbname='%s' user='%s' host='%s' port='%s' password='%s'" % (
            dbname, dbuser, dbhost, dbport, dbpass)
        )
        cur = conn.cursor()
        cur.execute("""select count(distinct user_id) from rooms_users_association_table""")
        the_count = cur.fetchone()[0]

    if dbtype == 'rdbms' and dbdriver.startswith('mysql'):
        import MySQLdb

        conn = MySQLdb.connect(passwd=dbpass, db=dbname, user=dbuser, host=dbhost, port=dbport)
        cur = conn.cursor()
        cur.execute("""select count(distinct user_id) from rooms_users_association_table""")
        the_count = cur.fetchone()[0]

r_host, r_port = config['cache']['host'].split(':')

r_db = 0
if 'db' in config['cache']:
    r_db = config['cache']['db']

r_server = redis.Redis(host=r_host, port=r_port, db=r_db)
r_server.set('users:online:inrooms', the_count)
