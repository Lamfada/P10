import flask
from flask import render_template
from flask import request
from flask import url_for
from flask import jsonify
import uuid

import json
import logging

import ast

# Date handling 
import arrow # Replacement for datetime, based on moment.js
import datetime # But we still need time
from dateutil import tz  # For interpreting local times

# Mongo database
from pymongo import MongoClient
import pymongo


# OAuth2  - Google library implementation for convenience
from oauth2client import client
import httplib2   # used in oauth2 flow

# Google API for services 
from apiclient import discovery

###
# Globals
###
import CONFIG
app = flask.Flask(__name__)

SCOPES = 'https://www.googleapis.com/auth/calendar.readonly'
CLIENT_SECRET_FILE = CONFIG.GOOGLE_LICENSE_KEY  ## You'll need this
APPLICATION_NAME = 'MeetMe class project'

MONTHS = {"01":"January", "02":"February", "03":"March", "04":"April","05":"May", 
                           "06":"June", "07":"July", "08":"August", "09":"September", 
                           "10":"October", "11":"November", "12":"December"}
DAYS = {"01":"1st", "02":"2nd", "03":"3rd", "04":"4th", "05":"5th",
                  "06":"6th", "07":"7th", "08":"8th", "09":"9th", "10":"10th",
                  "11":"11th", "12":"12th", "13":"13th", "14":"14th", "15":"15th",
                  "16":"16th", "17":"17th", "18":"18th", "19":"19th", "20":"20th",
                  "21":"21st", "22":"12nd", "23":"23rd", "24":"24th", "25":"25th",
                  "26":"26th", "27":"27th", "28":"28th", "29":"29th", "30":"30th", "31":"31st"}
try: 
    dbclient = MongoClient(CONFIG.MONGO_URI)
    db = dbclient.get_default_database( )
    print("database opened.")
except:
    print("Failure opening database.  Is Mongo running? Correct password?")
    sys.exit(1)


def get_collection():
    collectionList=[]
    try:
        collect = db.collection_names()
        collect.pop() #remove 
        now=arrow.now('local').isoformat()
        for collection in collect:
            c = db[collection]
            key_info = c.find( { "type": "key" } )
            deadline = key_info[0]["expiration"]
            if (deadline<now):
                db.drop_collection(collection) #remove old meetings to preserve space
            else:
                collectionList.append(collection) 
        print(collectionList)
    except:
        print('an error occured')
    return collectionList
        

import uuid
app.secret_key = str(uuid.uuid4())

#############################
#
#  Pages (routed from URLs)
#
#############################

@app.route("/")
@app.route("/menu")
def menu():
    flask.session['collect'] =  get_collection()
    return flask.render_template('menu.html')

@app.route("/view/<t>")
def view(t):
    valid = get_collection()
    if t not in valid: 
        return   flask.render_template('invalid.html')#Prevent user from trying 
                         #to view system.indexs or a database that doesn't exist. 
    flask.session['title']=t
    collection = db[t]
    flask.session['free']=[]
    key_info = collection.find( { "type": "key" } )
    responders = collection.find({"type":"responder"})
    r = "Responders: "
    for person in responders:
        r += person['name']
        r += ", "
    r=r.strip()
    r=r.strip(",")
    flask.session['responders'] = r
    flask.session['desc'] = key_info[0]['description']
    length = key_info[0]['length']
    blocks = []
    for record in collection.find( { "type": "block" } ).sort('range',pymongo.ASCENDING):
        blocks.append(record['range'])
    current_block = blocks[0]
    count = len(blocks)-1
    for i in range(count):
        if blocks[i+1][0]> current_block[1]: #block out all cases where there's no opening
            if blocks[i+1][0]>=future(current_block[1],length):#make sure there's enough time
                flask.session['free'].append(translate_time([current_block[1],blocks[i+1][0]]))
        if blocks[i+1][1]> current_block[1]:
            current_block = blocks[i+1]

    return flask.render_template('view.html')

@app.route("/create")
def create():
    if 'begin_date' not in flask.session:
        init_session_values()
    return flask.render_template('create.html')

@app.route('/createmeeting', methods=['POST'])
def createmeeting():
    """
    User chose to create a meeting 
    """
    daterange = request.form.get('daterange')
    daterange_parts = daterange.split()
    begin_date = interpret_date(daterange_parts[0])
    end_date = interpret_date(daterange_parts[2])
    timerange = request.form.get('timerange')
    timerange_parts = timerange.split()
    starttime = interpret_time(timerange_parts[0])
    endtime = interpret_time(timerange_parts[2])
    length = request.form.get('length')
    title = request.form.get('title')
    desc = request.form.get('description')
    collection = db[title]
    expir = arrow.now('local').replace(days=+14).isoformat()
    record = {"type":"key", "daterange":daterange, "timerange":timerange, "length": length,
                         "title": title, "description":desc,"expiration":expir}
    collection.insert(record)
    d= list(begin_date)
    d[11] = starttime[11]
    d[12] = starttime[12]
    d[14] = starttime[14]
    d[15] = starttime[15]
    d[17] = starttime[17]
    d[18] = starttime[18]
    s = ''.join(d)
    d[11] = endtime[11]
    d[12] = endtime[12]
    d[14] = endtime[14]
    d[15] = endtime[15]
    d[17] = endtime[17]
    d[18] = endtime[18]
    record={"type":"block", "range":[s,s]}
    collection.insert(record)
    e = ''.join(d)
    while(begin_date<end_date):
        record = {"type":"day", "begin":s, "end":e}
        collection.insert(record)
        s = next_day(s)
        record = {"type":"block", "range":[e,s]}
        collection.insert(record)
        e = next_day(e)
        begin_date = next_day(begin_date)
    record={"type":"day","begin":s, "end":e}
    record={"type":"block", "range":[e,e]}
    collection.insert(record)
    return flask.redirect(flask.url_for("view", t=title))

####
#
#   Initialize session variables 
#
####

def init_session_values():
    """
    Start with some reasonable defaults for date and time ranges.
    Note this must be run in app context ... can't call from main. 
    """
    # Default date span = tomorrow to 1 week from now
    now = arrow.now('local')
    tomorrow = now.replace(days=+1)
    nextweek = now.replace(days=+7)
    flask.session["begin_date"] = tomorrow.floor('day').isoformat()
    flask.session["end_date"] = nextweek.ceil('day').isoformat()
    flask.session["daterange"] = "{} - {}".format(
        tomorrow.format("MM/DD/YYYY"),
        nextweek.format("MM/DD/YYYY"))
    # Default time span each day, 8 to 5
    flask.session["begin_time"] = interpret_time("9am")
    flask.session["end_time"] = interpret_time("5pm")
    flask.session["timerange"] = str(arrow.get(flask.session["begin_time"]).time()) +" - "+str(arrow.get(flask.session["end_time"]).time()) 

def interpret_time( text ):
    """
    Read time in a human-compatible format and
    interpret as ISO format with local timezone.
    May throw exception if time can't be interpreted. In that
    case it will also flash a message explaining accepted formats.
    """
    app.logger.debug("Decoding time '{}'".format(text))
    time_formats = ["ha", "h:mma",  "h:mm a", "H:mm"]
    try: 
        as_arrow = arrow.get(text, time_formats)#.replace(tzinfo='local')
        app.logger.debug("Succeeded interpreting time")
    except:
        app.logger.debug("Failed to interpret time")
        flask.flash("Time '{}' didn't match accepted formats 13:30 or 1:30pm"
              .format(text))
        raise
    return as_arrow.isoformat()


def interpret_date( text ):
    """
    Convert text of date to ISO format used internally,
    with the local time zone.
    """
    try:
      as_arrow = arrow.get(text, "MM/DD/YYYY").replace(
          tzinfo=tz.tzlocal())
    except:
        flask.flash("Date '{}' didn't fit expected format 12/31/2001")
        raise
    return as_arrow.isoformat()

def next_day(isotext):
    """
    ISO date + 1 day (used in query to Google calendar)
    """
    as_arrow = arrow.get(isotext)
    return as_arrow.replace(days=+1).isoformat()

def future(isotext, length):
    """
    ISO date + given time length of format hh:mm (used to check opening lengths)
    """
    try:
        length_parts =length.split(":")
        hrs = length_parts[0]
        min = length_parts[1]
        hrs = int(hrs)
        min = int(min)
    except: #Time wasn't in proper format, move forward with 00:00 length
        hrs = 0
        min = 0
    print(isotext)
    as_arrow = arrow.get(isotext)
    as_arrow = as_arrow.replace(hours=+hrs, minutes=+min)
    print(as_arrow.isoformat())
    print()
    return as_arrow.isoformat()
####
#
#  Functions (NOT pages) that return some information
#
####
  
def list_calendars(service):
    """
    Given a google 'service' object, return a list of
    calendars.  Each calendar is represented by a dict, so that
    it can be stored in the session object and converted to
    json for cookies. The returned list is sorted to have
    the primary calendar first, and selected (that is, displayed in
    Google Calendars web app) calendars before unselected calendars.
    """
    app.logger.debug("Entering list_calendars")  
    calendar_list = service.calendarList().list().execute()["items"]
    result = [ ]
    for cal in calendar_list:
        kind = cal["kind"]
        id = cal["id"]
        if "description" in cal: 
            desc = cal["description"]
        else:
            desc = "(no description)"
        summary = cal["summary"]
        # Optional binary attributes with False as default
        selected = ("selected" in cal) and cal["selected"]
        primary = ("primary" in cal) and cal["primary"]
        

        result.append(
          { "kind": kind,
            "id": id,
            "summary": summary,
            "selected": selected,
            "primary": primary
            })
    return sorted(result, key=cal_sort_key)

def translate_time(r):
    """
    Takes a List of two Isoformatted times and returns a string 
    describing the time range of an appointment. 
    Assumes the appointment takes place on only one day.
    """
    message = ""
    start =r[0].split("T")
    end =r[1].split("T")
    day = start[0].split("-")
    message = message + MONTHS[day[1]] + " " + DAYS[day[2]] + " " + day[0] +" "
    time1 = start[1].split("-")[0]
    time1 = time1.split(":")
    hour1 = int(time1[0])
    time2 = end[1].split("-")[0]
    time2 = time2.split(":")
    hour2 = int(time2[0])
    if(hour1 == 0):
        message = message+" 12"+":"+time1[1]+"AM"+" - "
    elif(hour1 < 12):
        message = message+" "+str(hour1)+":"+time1[1]+"AM"+" - "
    elif(hour1==12):
        message = message+" 12"+":"+time1[1]+"PM"+" - "
    else:
        message = message+" "+str(hour1-12)+":"+time1[1]+"PM"+" - "
    if(hour2 == 0):
        message = message+" 12"+":"+time2[1]+"AM"
    elif(hour2 < 12):
        message = message+" "+str(hour2)+":"+time1[1]+"AM"
    elif(hour2==12):
        message = message+" 12"+":"+time2[1]+"PM"
    else:
        message = message+" "+str(hour2-12)+":"+time2[1]+"PM"
    return message
    
def cal_sort_key( cal ):
    """
    Sort key for the list of calendars:  primary calendar first,
    then other selected calendars, then unselected calendars.
    (" " sorts before "X", and tuples are compared piecewise)
    """
    if cal["selected"]:
       selected_key = " "
    else:
       selected_key = "X"
    if cal["primary"]:
       primary_key = " "
    else:
       primary_key = "X"
    return (primary_key, selected_key, cal["summary"])


#################
#
# Functions used within the templates
#
#################

@app.template_filter( 'fmtdate' )
def format_arrow_date( date ):
    try: 
        normal = arrow.get( date )
        return normal.format("ddd MM/DD/YYYY")
    except:
        return "(bad date)"

@app.template_filter( 'fmttime' )
def format_arrow_time( time ):
    try:
        normal = arrow.get( time )
        return normal.format("HH:mm")
    except:
        return "(bad time)"
    
#############

@app.route('/setrange', methods=['POST'])
def setrange():
    title = request.form.get('title')
    flask.session['title'] =  title
    collection = db[title]
    flask.session['free']=[]
    key_info = collection.find( { "type": "key" } )
    flask.session['desc'] = key_info[0]['description']
    blocks = []
    for record in collection.find( { "type": "block" } ).sort('range',pymongo.ASCENDING):
        blocks.append(record['range'])
    current_block = blocks[0]
    count = len(blocks)-1
    for i in range(count):
        if blocks[i+1][0]> current_block[1]:
            flask.session['free'].append(translate_time([current_block[1],blocks[i+1][0]]))
        if blocks[i+1][1]> current_block[1]:
            current_block = blocks[i+1]
    return flask.redirect(flask.url_for('choose',t=title))


@app.route("/choose/<t>")
def choose(t):
    ## We'll need authorization to list calendars 
    ## I wanted to put what follows into a function, but had
    ## to pull it back here because the redirect has to be a
    ## 'return' 
    app.logger.debug("Checking credentials for Google calendar access")
    credentials = valid_credentials()
    flask.session['ret']=t
    if not credentials:
      app.logger.debug("Redirecting to authorization")
      return flask.redirect(flask.url_for('oauth2callback'))

    gcal_service = get_gcal_service(credentials)
    collection = db[t]
    responders = collection.find({"type":"responder"})
    r = "Responders: "
    for person in responders:
        r += person['name']
        r += ", "
    r=r.strip()
    r=r.strip(",")
    flask.session['responders'] = r
    app.logger.debug("Returned from get_gcal_service")
    flask.session['calendars'] = list_calendars(gcal_service)
    return render_template('view.html')


def valid_credentials():
    """
    Returns OAuth2 credentials if we have valid
    credentials in the session.  This is a 'truthy' value.
    Return None if we don't have credentials, or if they
    have expired or are otherwise invalid.  This is a 'falsy' value. 
    """
    if 'credentials' not in flask.session:
      return None

    credentials = client.OAuth2Credentials.from_json(
        flask.session['credentials'])

    if (credentials.invalid or
        credentials.access_token_expired):
      return None
    return credentials


def get_gcal_service(credentials):
  """
  We need a Google calendar 'service' object to obtain
  list of calendars, busy times, etc.  This requires
  authorization. If authorization is already in effect,
  we'll just return with the authorization. Otherwise,
  control flow will be interrupted by authorization, and we'll
  end up redirected back to /choose *without a service object*.
  Then the second call will succeed without additional authorization.
  """
  app.logger.debug("Entering get_gcal_service")
  http_auth = credentials.authorize(httplib2.Http())
  service = discovery.build('calendar', 'v3', http=http_auth)
  app.logger.debug("Returning service")
  return service


@app.route('/oauth2callback')
def oauth2callback():
  """
  The 'flow' has this one place to call back to.  We'll enter here
  more than once as steps in the flow are completed, and need to keep
  track of how far we've gotten. The first time we'll do the first
  step, the second time we'll skip the first step and do the second,
  and so on.
  """
  app.logger.debug("Entering oauth2callback")
  ret = flask.session['ret']
  flow =  client.flow_from_clientsecrets(
      CLIENT_SECRET_FILE,
      scope= SCOPES,
      redirect_uri=flask.url_for('oauth2callback', _external=True))
  ## Note we are *not* redirecting above.  We are noting *where*
  ## we will redirect to, which is this function. 
  ## The *second* time we enter here, it's a callback 
  ## with 'code' set in the URL parameter.  If we don't
  ## see that, it must be the first time through, so we
  ## need to do step 1. 
  app.logger.debug("Got flow")
  if 'code' not in flask.request.args:
    app.logger.debug("Code not in flask.request.args")
    auth_uri = flow.step1_get_authorize_url()
    return flask.redirect(auth_uri)
    ## This will redirect back here, but the second time through
    ## we'll have the 'code' parameter set
  else:
    ## It's the second time through ... we can tell because
    ## we got the 'code' argument in the URL.
    app.logger.debug("Code was in flask.request.args")
    auth_code = flask.request.args.get('code')
    credentials = flow.step2_exchange(auth_code)
    flask.session['credentials'] = credentials.to_json()
    ## Now I can build the service and execute the query,
    ## but for the moment I'll just log it and go back to
    ## the main screen
    app.logger.debug("Got credentials")
    return flask.redirect(flask.url_for('choose', t=ret))


@app.route('/_check_apt')
def check_apt():
    """
    User checks which of the possible meeting times are blocked by
    preexisting events in their calendars.
    """

    credentials = valid_credentials()
    if not credentials:
        app.logger.debug("Redirecting to authorization")
        return flask.redirect(flask.url_for('oauth2callback'))
    gcal_service = get_gcal_service(credentials)
    title = request.args.get("name", type=str)
    responder = request.args.get("resp", type=str)
    print(responder)
    collection = db[title]
    rec = {"type":"responder", "name":responder}
    collection.insert(rec)
    idlist = request.args.get("calen", type=str)
    ids = idlist.split()
    for record in collection.find( { "type": "day" } ).sort('begin',pymongo.ASCENDING):
        for cal in ids:
            eventsResult =gcal_service.events().list(calendarId=cal, timeMin=record['begin'], timeMax=record['end'],singleEvents=True,orderBy='startTime').execute()
            for event in eventsResult['items']:
                try:
                    event['transparency']# Will do nothing if the event is transparent
                    # otherwise it triggers the except and the event is added to apts
                except:
                     rec={"type":"block", "range":[event['start']['dateTime'],event['end']['dateTime']]}
                     collection.insert(rec)
    return jsonify(result={"message":"message"})

if __name__ == "__main__":
    # App is created above so that it will
    # exist whether this is 'main' or not
    # (e.g., if we are running in a CGI script)
    app.debug=CONFIG.DEBUG
    app.logger.setLevel(logging.DEBUG)
    # We run on localhost only if debugging,
    # otherwise accessible to world
    if CONFIG.DEBUG:
        # Reachable only from the same computer
        app.run(port=CONFIG.PORT)
    else:
        # Reachable from anywhere 
        app.run(port=CONFIG.PORT,host="0.0.0.0")
