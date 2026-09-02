from core.plugins import SectionManager
from core.pipeline.adapter import SectionPipelineAdapter

class Gate:
    def preflight(self,*a,**k):
        class R: allowed=True; reason=''; matched=(); fingerprint='fp'
        return R()
class Queue:
    def enqueue_article(self,i,payload,**kw): return 'job:'+i
class AI:
    def article_package(self,*a,**kw):
        class R: data={'title':'x'}
        return R()
class Pub:
    def publish(self,*a,**kw): return {'status':'published'}

def test_builtin_sections_and_future_plugin_shape():
    m=SectionManager()
    assert all(x in m.list() for x in ('blogger','news','sports'))
    m.registry.register(type('X',(),{'name':'weather','kind':'content'})())
    assert m.get('weather') is not None

def test_common_adapter():
    p=SectionPipelineAdapter('news',Gate(),Queue(),AI(),Pub())
    assert p.submit('1','article')['status']=='queued'
    assert p.process('article')['title']=='x'
    assert p.publish('1','blogger','body')['status']=='published'
