from blogsetup import GetCurrentBlog

import logging
import re

from google.appengine.ext import ndb
from google.appengine.ext.ndb import query 

class Posts(ndb.Model):
  title = ndb.StringProperty()
  text = ndb.TextProperty()
  pic = ndb.StringProperty()
  postid = ndb.StringProperty()
  lastmodified = ndb.StringProperty()
  snippet = ndb.TextProperty()
  visible = ndb.BooleanProperty()
  code = ndb.StringProperty()
  blog = ndb.StringProperty()
  @property
  def nice_date(x):
    months = 'January,February,March,April,May,June,July,August,September,October,November,December'.split(',')
    date = Posts.get_small_date(x)
    year,month,day = int(date[:4]),int(date[4:6]),int(date[6:])
    return '%s %d, %d' % (months[month-1], day, year)
  created = ndb.DateTimeProperty(auto_now_add=True)
  small_name = ndb.ComputedProperty(lambda self: Posts.get_small_name(self))
  small_date = ndb.ComputedProperty(lambda self: Posts.get_small_date(self))
  @staticmethod
  def get_small_name(x):
    return re.sub('\s+','-', re.sub('[^a-z0-9 ]','',x.title.lower()))
  @staticmethod
  def get_small_date(x):
    return x.created.strftime("%Y%m%d")
  @staticmethod
  def GetAllPosts(req, currentBlog):
    q = Posts.gql("WHERE blog=:1 order by created DESC", currentBlog.subdomain)
    return q.fetch(1000, batch_size=1000)
  @staticmethod
  def GetPostById(pid, currentBlog):
    q = Posts.gql("WHERE postid=:1 and blog=:2", pid, currentBlog.subdomain)
    return q.get()
  @staticmethod
  def GetPostBySmallName(small_name, currentBlog):
    q = Posts.gql("WHERE small_name=:1 and blog=:2", small_name, currentBlog.subdomain)
    return q.get()
  @staticmethod
  def GetFrontpage(currentBlog):
    q = Posts.gql("WHERE visible=:1 and blog=:2", True, currentBlog.subdomain)
    return q.fetch(1000, batch_size=1000)
