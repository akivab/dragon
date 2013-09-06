from google.appengine.ext import ndb
from google.appengine.api import users
import logging

BLOG_FOLDER_ID = '0Byj8ccoezKFWNVFNb0RTSEZfcGs'
BLOG_USER_ID = 'akiva.bamberger'
BLOG_TITLE = 'rm -rf /'
BLOG_IMAGE = '/r/images/me.jpg'
BLOG_SNIPPET = 'thoughts and projects by akiva'
DISQUS_ID = 'rmrf'
GOOGLE_ANALYTICS_ID = 'UA-40663280-1'
GOOGLE_ANALYTICS_SITE = 'rm-rfslash.appspot.com'


class Blog(ndb.Model):
  folder = ndb.StringProperty()
  user = ndb.UserProperty()
  title = ndb.StringProperty()
  image = ndb.StringProperty()
  snippet = ndb.StringProperty()
  disqusId = ndb.StringProperty()
  gaeId = ndb.StringProperty()
  gaeSite = ndb.StringProperty()
  subdomain = ndb.StringProperty()

def GetCurrentBlog(subdomain):
  return Blog.query(Blog.subdomain==subdomain).get()
 
def IsLoggedIn(currentBlog, testing=True):
  user = users.get_current_user()
  if testing: return True if user else False
  return user and currentBlog and user.user_id() == currentBlog.user.user_id()

