import jinja2
import json
import httplib2
import os
import re
import urllib2
import markdown
import contentparser
import blogsetup
import logging
import datetime
from random import randint

from apiclient.discovery import build
from oauth2client.appengine import oauth2decorator_from_clientsecrets
from oauth2client.client import AccessTokenRefreshError
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

jinja_environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

CLIENT_SECRETS = os.path.join(os.path.dirname(__file__), 'client_secrets.json')

service = build("drive", "v2")
decorator = oauth2decorator_from_clientsecrets(
    CLIENT_SECRETS,
    scope='https://www.googleapis.com/auth/drive')

class Posts(ndb.Model):
  title = ndb.StringProperty()
  text = ndb.TextProperty()
  pic = ndb.StringProperty()
  postid = ndb.StringProperty()
  lastmodified = ndb.StringProperty()
  snippet = ndb.TextProperty()
  visible = ndb.BooleanProperty()
  code = ndb.StringProperty()
  @staticmethod
  def get_small_name(x):
    return re.sub('\s+','-', re.sub('[^a-z0-9 ]','',x.title.lower()))
  @staticmethod
  def get_small_date(x):
    return x.created.strftime("%Y%m%d")
  @property
  def nice_date(x):
    months = 'January,February,March,April,May,June,July,August,September,October,November,December'.split(',')
    date = Posts.get_small_date(x)
    year,month,day = int(date[:4]),int(date[4:6]),int(date[6:])
    return '%s %d, %d' % (months[month-1], day, year)
  created = ndb.DateTimeProperty(auto_now_add=True)
  small_name = ndb.ComputedProperty(lambda self: Posts.get_small_name(self))
  small_date = ndb.ComputedProperty(lambda self: Posts.get_small_date(self))
  @classmethod
  def getPostById(cls, pid):
    return Posts.gql("WHERE postid=:1", pid).get()


def Redirect(req, msg, url):
  tpl = "%s <script>setTimeout(function(){ window.location.href='%s';}, 100);</script>"
  req.response.out.write(tpl % (msg, url))

def MarkdownText(content):
  return markdown.markdown(content,
      extensions=['tables', 'nl2br', 'fenced_code','codehilite', 'emoticons'],
      extension_configs={'emoticons': [
        ('BASE_URL', '/r/emoticons/'),
        ('FILE_EXTENSION', 'png'),
      ]})

def IsLoggedIn(user):
  return user and user.nickname().lower() == blogsetup.BLOG_USER_ID.lower()

def TemplateValues(template_values):
  defaults = {
    'mainimg': blogsetup.BLOG_IMAGE,
    'maintitle': blogsetup.BLOG_TITLE,
    'mainsnippet': blogsetup.BLOG_SNIPPET,
    'disqus_id': blogsetup.DISQUS_ID,
    'gae_id': blogsetup.GOOGLE_ANALYTICS_ID,
    'gae_site': blogsetup.GOOGLE_ANALYTICS_SITE
  }
  for i in defaults: template_values[i] = defaults[i]
  return template_values

class MainHandler(webapp.RequestHandler):
  def get(self):
    posts = Posts.gql("WHERE visible=:1 order by created DESC", True)
    logged_in = IsLoggedIn(users.get_current_user())
    edit_mode = True if self.request.get('edit') and logged_in else False
    template_values = TemplateValues({
      'published': posts,
      'edit_mode': edit_mode,
      'logged_in': logged_in,
    })
    template = jinja_environment.get_template('home.html')
    self.response.out.write(template.render(template_values))

class AdminHandler(webapp.RequestHandler):
  @decorator.oauth_aware
  def get(self):
    newfiles = files = []
    user = users.get_current_user() 
    try:
      logged_in = decorator.has_credentials()
      url = decorator.authorize_url()
    except AccessTokenRefreshError:
      self.redirect('/')
    if not IsLoggedIn(user):
      logged_in = False
      url = users.create_login_url()
    posts = Posts.gql("order by created DESC")
    postids = {}
    for i in posts:
      postids[i.postid] = i.lastmodified
    published = [p for p in posts if p.visible]
    unpublished = [p for p in posts if not p.visible]
    if logged_in:
      files = UpdateHandler.listFiles(self, decorator.http())
      if files:
        newfiles = [f for f in files if (f['id'] not in postids
            or postids[f['id']] != f['modifiedDate'])]
    template_values = TemplateValues({
      'logged_in': logged_in,
      'url': url,
      'published': published,
      'unpublished': unpublished,
      'toupdate': newfiles
      })
    template = jinja_environment.get_template('admin.html')
    self.response.out.write(template.render(template_values))

class UpdateHandler(webapp.RequestHandler):
  @classmethod
  def listFiles(cls, req, http):
    items = None
    try:
      query = "'%s' in parents" % blogsetup.BLOG_FOLDER_ID
      # Get all files in Blog folder
      req = service.files().list(q=query)
      files = req.execute(http)
      items = files['items']
    except AccessTokenRefreshError:
      pass
    return items

  @decorator.oauth_required
  def get(self):
    fileId = self.request.get('id')
    try:
      http = decorator.http()
      if fileId:
        self.updateFile(fileId, http)
        return
      Redirect(self, 'Nothing to see here.', '/')
    except AccessTokenRefreshError:
      self.redirect('/')

  def updateFile(self, fileId, http):
    forced = self.request.get('force')
    req = service.files().get(fileId=fileId)
    item = req.execute(http)
    itemKeys = ['title', 'modifiedDate', 'exportLinks']
    def all_in():
      for i in itemKeys:
        if i not in item:
          return False
      return True

    def error(msg):
      self.response.headers['Content-Type'] = 'text/text'
      self.response.out.write(msg)

    if not all_in():
      error('Not all of [%s] found in item!<br />%s'%
          (','.join(itemKeys), str(item)))
      return
      
    post = Posts.getPostById(fileId)
    title = item['title']
    lastmodified = item['modifiedDate']
    if post and post.lastmodified == lastmodified and not forced:
      Redirect(self, 'No modification needed!', '/get?id=%s' % fileId)
      return
    exportLinks = item['exportLinks']
    htmlResp, htmlContent = http.request(exportLinks['text/html'])
    textResp, textContent = http.request(exportLinks['text/plain'])
    if textResp.status != 200 or htmlResp.status != 200:
      error('Error retrieving page!')
      return

    htmlContent = unicode(htmlContent, errors='ignore')
    textContent = unicode(textContent, errors='ignore')
    content = contentparser.analyze(textContent, htmlContent)
    text = MarkdownText(content)
    snippet = ''
    pic = '/r/defaults/%d.jpg' % randint(1,3)
    if post:
      post.text = text
      post.lastmodified = lastmodified
    else:
      post = Posts(title=title,
          text=text,
          pic=pic,
          snippet=snippet,
          lastmodified=lastmodified,
          postid=fileId)
    post.put()
    Redirect(self, 'Loading page.', '/get?id=%s' % fileId)

class BlogHandler(webapp.RequestHandler):
  def findPost(self):
    match = re.match('/post/(\d+)/([-a-z0-9]+)', self.request.path)
    if not match:
      match = re.match('/post/([-a-z0-9]+)', self.request.path)
      stitle = match.group(1)
      if stitle:
        return Posts.gql("WHERE small_name=:1", stitle).get()
    else:
      sdate = match.group(1)
      stitle = match.group(2)
      if sdate and stitle:
        return Posts.query(Posts.small_date==sdate,
            Posts.small_name==stitle).get()
    return None
  def get(self, *args):
    if re.match('/post', self.request.path):
      post = self.findPost()
      if not post:
        self.error(404)
        return
    else:
      fileId = self.request.get('id')
      post = Posts.getPostById(fileId)
    if not post:
      self.error(404)
      return
    edit_mode = True if self.request.get('edit') else False
    can_show = True if post and post.visible else False
    has_code = True if (post and post.code and len(post.code) > 0 and
        post.code == self.request.get('code')) else False
    is_main_link = True if post.title.lower() in ('resume', 'about') else False
    logged_in = IsLoggedIn(users.get_current_user())
    if not can_show and not logged_in and not is_main_link and not has_code:
      self.error(404)
      return
    template_values = TemplateValues({
      'post': post,
      'edit_mode' :edit_mode,
      'logged_in': logged_in,
      'is_main_link': is_main_link
    })
    template = jinja_environment.get_template('post.html')
    self.response.out.write(template.render(template_values))
    return
  def post(self, *args):
    fileId = self.request.get('id')
    editMode = visible = created = code = pic = snippet = None
    if self.request.path == '/edit':
      code = self.request.get('code')
      pic = self.request.get('pic')
      snippet = self.request.get('snippet')
      editMode = True
    elif self.request.path == '/publish':
      visible = True
      created = datetime.datetime.now()
    user = users.get_current_user()
    post = Posts.getPostById(fileId)
    logging.info('publishing %s %s' % (fileId, post.title))
    if not post or not IsLoggedIn(user):
      self.error(404)
      return
    if visible is not None: post.visible = visible 
    if code: post.code = code 
    if pic: post.pic = pic 
    if created: post.created = created
    if snippet: post.snippet = snippet 
    post.put()
    if not editMode:
      self.response.out.write('Published post.')
    else:
      Redirect(self, 'Edited post.', '/')

def main():
  application = webapp.WSGIApplication(
      [
       ('/', MainHandler),
       ('/admin', AdminHandler),
       ('/update', UpdateHandler),
       ('/(get|publish|edit)', BlogHandler),
       ('/post/.*', BlogHandler),
       (decorator.callback_path, decorator.callback_handler()),
      ],
      debug=False)
  run_wsgi_app(application)



if __name__ == '__main__':
  main()
