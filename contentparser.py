from HTMLParser import HTMLParser
import re

class MediaExtractor(HTMLParser):
  def __init__(self, text):
    self.text = None
    self.count = {}
    HTMLParser.__init__(self)
    self.text = text + '\n'
  
  def handle_starttag(self, tag, attrs):
    if tag in ('a','img'):
      src = None
      for i in attrs:
        if i[0] == 'src': src = i[1]
        if i[0] == 'href': src = i[1]
      if tag == 'a': tag = 'link'
      if not tag in self.count: self.count[tag] = 1
      if src:
        self.text += '[%s%d]: %s\n' % (tag, self.count[tag], src)
        self.count[tag] += 1

class SnippetExtractor(HTMLParser):
  LIMIT = 400
  def __init__(self):
    self.snippet = ''
    self.overflow = False
    HTMLParser.__init__(self)

  def handle_starttag(self, tag, attrs):
    self.record = (tag not in ('style', 'script'))
  def handle_endtag(self, tag):
    self.record = False
  def handle_data(self, data):
    self.snippet += data if len(self.snippet) < self.LIMIT else ''
    self.overflow = self.overflow or len(data) + len(self.snippet) > self.LIMIT


def analyze(text, html):
  m = MediaExtractor(text)
  m.feed(html)
  return m.text

def snippet(text):
  s = SnippetExtractor()
  s.feed(text)
  s.snippet += '...' if s.overflow else ''
  return s.snippet
