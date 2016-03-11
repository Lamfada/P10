"""
Configuration of 'memos' Flask app. 
Edit to fit development or deployment environment.

"""

### Flask settings
PORT=6709        # The port I run Flask on
GOOGLE_LICENSE_KEY = ".goog_app_key.json"
DEBUG = False     # Set to False on ix

### MongoDB settings
MONGO_PORT=61375 #  Probably best to use the same port as you use on ix

### The following are for a Mongo user you create for accessing your
### memos database.  It should not be the same as your database administrator
### account. 
MONGO_PW = "user"  
MONGO_USER = "password"
MONGO_URL = "mongodb://{}:{}@ds061375.mongolab.com:{}/zava".format(MONGO_USER,MONGO_PW,MONGO_PORT)
#MONGO_URI = "mongodb://{}:{}@ds061375.mongolab.com:61375/zava".format(MONGO_USER,MONGO_PW)
MONGO_URI = "mongodb://user:password@ds061375.mongolab.com:61375/zava"