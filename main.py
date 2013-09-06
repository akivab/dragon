from blogsetup import Blog, IsLoggedIn, GetCurrentBlog
from posts import Posts
from random import randint
import contentparser
import datetime
import httplib2
import jinja2
import json
import logging
import markdown
import os
import re
import urllib2
import webapp2
from webapp2_extras import routes

from apiclient.discovery import build
from oauth2client.appengine import oauth2decorator_from_clientsecrets
from oauth2client.client import AccessTokenRefreshError
from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template

jinja_environment = jinja2.Environment(
    autoescape=False, extensions=['jinja2.ext.autoescape'],
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)))

CLIENT_SECRETS = os.path.join(os.path.dirname(__file__), 'client_secrets.json')

service = build("drive", "v2")
decorator = oauth2decorator_from_clientsecrets(
    CLIENT_SECRETS,
    scope='https://www.googleapis.com/auth/drive')

def Redirect(req, msg, url):
  """Redirects to a URL after 100ms, first displaying a message.

    Args:
        req: The webapp2.RequestHandler object used to redirect.
        msg: The message to display.
        url: The URL to redirect to.
  """
  tpl = "%s <script>setTimeout(function(){  window.location.href='%s';}, 100);\
  </script>"
  req.response.out.write(tpl % (msg, url))

def ListFiles(http, folderId):
  """Lists files in a Google Drive folder.

    Args:
        http: The http Object used to make the request.
        folderId: The folder ID for the folder used to make the request.
    Returns:
        A list of items in the folder, or None if an error occured.
  """
  items = None
  try:
    query = "'%s' in parents" % folderId
    req = service.files().list(q=query)
    files = req.execute(http)
    items = files['items']
  except AccessTokenRefreshError:
    pass
  return items

def MarkdownText(content):
  """Returns text run through a Markdown parser.

    Args:
        content: The content to run through the parser.
    Returns:
        The parsed content.
  """
  return markdown.markdown(content,
      extensions=['tables', 'nl2br', 'fenced_code','codehilite', 'emoticons'],
      extension_configs={'emoticons': [
        ('BASE_URL', '/r/emoticons/'),
        ('FILE_EXTENSION', 'png'),
      ]})

def TemplateValues(template_values, blog=None):
  """Returns a dict of the values for a blog.

    Args:
      template_values: the dict to populate
      blog: the blog to use
    Returns:
        A dict of the template values
  """
  if not blog: return {}
  defaults = {
    'mainimg': blog.image,
    'maintitle': blog.title,
    'mainsnippet': blog.snippet,
    'disqus_id': blogsetup.DISQUS_ID,
    'gae_id': blogsetup.GOOGLE_ANALYTICS_ID,
    'gae_site': blogsetup.GOOGLE_ANALYTICS_SITE
  }
  for i in defaults: template_values[i] = defaults[i]
  return template_values

def GetBlogUrl(req, subdomain):
  return 'http://' + subdomain + '.' + req.request.host

class RedirectHandler(webapp2.RequestHandler):
  def get(self, **kwargs):
    if self.request.get('blog'):
      subdomain = self.request.get('blog')
      Redirect(self, 'Redirecting', GetBlogUrl(self, subdomain))
    else:
      Redirect(self, 'Not found.', '/')

class CreateBlogHandler(webapp2.RequestHandler):
  @decorator.oauth_required
  def get(self, **kwargs):
    http = decorator.http()
    req = service.files().list(
         q="'root' in parents and mimeType='application/vnd.google-apps.folder'")
    items = req.execute(http)
    """
    items = json.loads(open("data.json", "r").read())
    """
    template_values = {'posts': items['items'], 'host': 'http://' + self.request.host}
    template = jinja_environment.get_template('create_blog.html')
    self.response.out.write(template.render(template_values))
  def post(self, **kwargs):
    if not users.get_current_user():
      return
    params = {'user': users.get_current_user()}
    keys = 'snippet,folder,title,image,subdomain'.split(',')
    for i in keys:
      params[i] = self.request.get(i)
    if ('subdomain' not in params or not params['subdomain'] or
        Blog.gql('WHERE subdomain=:1',params['subdomain']).get()):
      return Redirect(self, 'Cannot create blog.', '/')
    blog = Blog(**params)
    blog.put()

    Redirect(self, 'Blog created.', GetBlogUrl(self, blog.subdomain))

class HomePageHandler(webapp2.RequestHandler):
  def get(self, **kwargs):
    template_values = {}
    if not users.get_current_user():
      template_values['login'] = users.create_login_url('/')
    else:
      user = users.get_current_user()
      template_values['blogs'] = Blog.gql('WHERE user=:1', user).fetch(100)
    template = jinja_environment.get_template('index.html')
    self.response.out.write(template.render(template_values))

class MainHandler(webapp2.RequestHandler):
  def get(self, subdomain=None):
    logging.info("In MainHandler")
    currentBlog = GetCurrentBlog(subdomain)
    if not currentBlog:
      return Redirect(self, 'No blog found at %s.' % subdomain,
          'http://' +
          self.request.host[len(subdomain)+1:] +
          '/create?blog=' + subdomain)
    posts = Posts.GetFrontpage(currentBlog)
    logged_in = IsLoggedIn(currentBlog)
    edit_mode = True if self.request.get('edit') and logged_in else False
    template_values = TemplateValues({
      'published': posts,
      'edit_mode': edit_mode,
      'logged_in': logged_in,
    }, currentBlog)
    template = jinja_environment.get_template('home.html')
    self.response.out.write(template.render(template_values))

class AdminHandler(webapp2.RequestHandler):
  @decorator.oauth_aware
  def get(self, subdomain=None):
    newfiles = files = []
    user = users.get_current_user()
    currentBlog = GetCurrentBlog(subdomain)
    if not currentBlog:
      Redirect(self, '/', 'No blog found.')
    try:
      logged_in = decorator.has_credentials()
      url = decorator.authorize_url()
    except AccessTokenRefreshError:
      self.redirect('/')
    if not IsLoggedIn(currentBlog):
      logged_in = False
      url = users.create_login_url()
    published, unpublished, newfiles = GetPosts(self, currentBlog, decorator)
    template_values = TemplateValues({
      'logged_in': logged_in,
      'url': url,
      'published': published,
      'unpublished': unpublished,
      'toupdate': newfiles
      }, currentBlog)
    template = jinja_environment.get_template('admin.html')
    self.response.out.write(template.render(template_values))
  @staticmethod
  def GetPosts(req, blog, decorator=None):
    posts = Posts.GetAllPosts(req, currentBlog)
    postids = {}
    for i in posts:
      postids[i.postid] = i.lastmodified
    published = [p for p in posts if p.visible]
    unpublished = [p for p in posts if not p.visible]
    newfiles = None
    if IsLoggedIn(blog) and decorator:
      files = ListFiles(decorator.http(), blog.folder)
      if files:
        newfiles = [f for f in files if (f['id'] not in postids
            or postids[f['id']] != f['modifiedDate'])]
    return published, unpublished, newfiles

class UpdateHandler(webapp2.RequestHandler):
  @decorator.oauth_required
  def get(self, subdomain=None):
    logging.info("In UpdateHandler")
    fileId = self.request.get('id')
    currentBlog = GetCurrentBlog(subdomain)
    logging.error(str(currentBlog.key))
    if not currentBlog:
      Redirect(self, '/', 'No blog found.')
    try:
      http = decorator.http()
      if fileId:
        return self.updateFile(fileId, http, currentBlog)
      Redirect(self, 'Nothing to see here.', '/')
    except AccessTokenRefreshError:
      self.redirect('/')

  def updateFile(self, fileId, http, currentBlog):
    forced = self.request.get('force')
    req = service.files().get(fileId=fileId)
    item = req.execute(http)
    post = Posts.GetPostById(fileId, currentBlog)
    if post and post.postid != fileId:
      logging.error('No post!')
      post = None
    if not 'title' in item and 'modifiedDate' in item and 'exportLinks' in item:
      return self.error(404)
    title = item['title']
    lastmodified = item['modifiedDate']
    if post and post.lastmodified == lastmodified and not forced:
      return Redirect(self, 'No modifcation needed!', '/get?id=%s' % fileId)
    exportLinks = item['exportLinks']
    htmlResp, htmlContent = http.request(exportLinks['text/html'])
    textResp, textContent = http.request(exportLinks['text/plain'])
    if textResp.status != 200 or htmlResp.status != 200:
      return self.error(404)

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
          postid=fileId,
          blog=currentBlog.subdomain,
          visible=False)
    post.put()
    Redirect(self, 'Loading page.', '/get?id=%s' % fileId)

class BlogHandler(webapp2.RequestHandler):
  def findPost(self, currentBlog):
    match = re.match('/post/(\d+)/([-a-z0-9]+)', self.request.path)
    if not match:
      match = re.match('/post/([-a-z0-9]+)', self.request.path)
      stitle = match.group(1)
      if stitle:
        return Posts.GetPostBySmallName(stitle, currentBlog)
    else:
      sdate = match.group(1)
      stitle = match.group(2)
      if sdate and stitle:
        return Posts.query(Posts.small_date==sdate,
            Posts.small_name==stitle).get()
    return None
  def get(self, subdomain=None):
    logging.info("In BlogHandler")
    currentBlog = GetCurrentBlog(subdomain)
    if not currentBlog:
      return self.error(404)
    if re.match('/post', self.request.path):
      post = self.findPost(currentBlog)
      if not post: return self.error(404)
    else:
      fileId = self.request.get('id')
      post = Posts.GetPostById(fileId, currentBlog)
    if not post: return self.error(404)
    edit_mode = True if self.request.get('edit') else False
    can_show = True if post and post.visible else False
    has_code = True if (post and post.code and len(post.code) > 0 and
        post.code == self.request.get('code')) else False
    is_main_link = True if post.title.lower() in ('resume', 'about') else False
    logged_in = IsLoggedIn(currentBlog)
    if not can_show and not logged_in and not is_main_link and not has_code:
      return self.error(404)
    template_values = TemplateValues({
      'post': post,
      'edit_mode' :edit_mode,
      'logged_in': logged_in,
      'is_main_link': is_main_link
    }, currentBlog)
    template = jinja_environment.get_template('post.html')
    self.response.out.write(template.render(template_values))
    return
  def post(self, subdomain=None):
    fileId = self.request.get('id')
    currentBlog = GetCurrentBlog(subdomain)
    if not currentBlog:
      return self.error(404)
    post = Posts.GetPostById(fileId, currentBlog)
    if not post or not IsLoggedIn(currentBlog):
      return self.error(404)
    editMode = visible = created = code = pic = snippet = None
    if self.request.path == '/edit':
      code = self.request.get('code')
      pic = self.request.get('pic')
      snippet = self.request.get('snippet')
      editMode = True
    elif self.request.path == '/publish':
      visible = True
      created = datetime.datetime.now()
    elif self.request.path == '/unpublish':
      visible = False
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

class EditBlogHandler(webapp2.RequestHandler):
  def post(self, subdomain=None):
    currentBlog = GetCurrentBlog(subdomain)
    if not currentBlog or not IsLoggedIn(currentBlog):
      return self.error(404)
    if self.request.get('title'):
      currentBlog.title = self.request.get('title')
    if self.request.get('image'):
      currentBlog.image = self.request.get('image')
    if self.request.get('snippet'):
      currentBlog.snippet = self.request.get('snippet')
    currentBlog.put()
    Redirect(self, 'Edited page', '/')



app = webapp2.WSGIApplication([
    routes.DomainRoute('<subdomain:(?!www\.)[^.]+>.<:(dragon-blog\.appspot\.com|localhost|palmyrainmotion\.com)>', [
        webapp2.Route('/', MainHandler, 'main'),
        webapp2.Route('/admin', AdminHandler, 'admin'),
        webapp2.Route('/edit_blog', EditBlogHandler, 'admin'),
        webapp2.Route('/update', UpdateHandler, 'update'),
        webapp2.Route('/<:(get|unpublish|publish|edit|(post/.*))>', BlogHandler, 'blog'),
    ]),
    routes.DomainRoute('<url:.*>', [
        webapp2.Route('/create', CreateBlogHandler, 'create-blog'),
        webapp2.Route('/subdomain', RedirectHandler, 'redirect'),
        webapp2.Route('/', HomePageHandler, 'home-page'),
    ]),
    (decorator.callback_path, decorator.callback_handler()),
], debug=True)
