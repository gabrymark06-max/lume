"""Viste editoriali dai cataloghi collegati e metadati pubblici, senza chiavi Veezie."""
import datetime
import concurrent.futures
import json
import re
from urllib.parse import urlencode, urljoin
from bs4 import BeautifulSoup


GENRES = [('azione','Azione'),('avventura','Avventura'),('animazione','Animazione'),('commedia','Commedia'),('crime','Crime'),('documentario','Documentario'),('drammatico','Drammatico'),('famiglia','Famiglia'),('fantasy','Fantasy'),('storico','Storico'),('horror','Horror'),('musicale','Musicale'),('mistero','Mistery'),('romantico','Romantico'),('fantascienza','Fantascienza'),('film-tv','Film per la TV'),('thriller','Thriller'),('guerra','Guerra'),('western','Western')]
PLATFORMS = [('netflix','Netflix'),('prime','Prime Video'),('disney','Disney+'),('apple','Apple TV+'),('now','NOW'),('paramount','Paramount+'),('crunchyroll','Crunchyroll')]
EDITORIAL = [('christmas','Film Di Natale'),('popular','Popolari'),('toprated','I Più Votati'),('cinema','Al Cinema'),('disney','Walt Disney'),('superheroes','Supereroi')]


def payload_records(text, hydration):
    data = hydration(text)
    decoder = json.JSONDecoder()
    records, seen = [], set()
    for match in re.finditer(r'\{"(?:id|kind|title)"\s*:', data):
        try:
            item = decoder.raw_decode(data, match.start())[0]
        except ValueError:
            continue
        if not isinstance(item, dict) or not item.get('title') or not item.get('id') or not item.get('kind'):
            continue
        key = str(item['id'])
        if key not in seen:
            records.append(item)
            seen.add(key)
        if len(records) >= 1500:
            break
    return records


def enrich_cards(items, markup, hydration, base):
    records = payload_records(markup, hydration)
    index = {str(r.get('legacyId') or r['id']): r for r in records}
    for item in items:
        match = re.search(r'/(?:titles/)?(\d+)-', item['url'])
        record = index.get(match.group(1)) if match else None
        if not record:
            continue
        item.update(kind=record.get('kind') or item.get('kind'), year=record.get('year') or item.get('year'),
                    description=record.get('plot') or item.get('description',''), genres=record.get('genres') or [],
                    rating=record.get('rating'), runtime=record.get('durationMin'), platforms=record.get('networks') or [],
                    imdb=record.get('imdbId'), popularity=record.get('popularity'), views=record.get('views'),
                    in_cinema=bool(record.get('inCinema')), release_date=record.get('releaseDate'), title_image=record.get('logoUrl'))
        for key, source in [('poster','posterUrl'),('backdrop','backdropUrl')]:
            if record.get(source):
                item[key] = urljoin(base, record[source])
        if record.get('scTrailer') and re.fullmatch(r'tt\d+',str(record.get('imdbId',''))):
            item['trailer']={'url':'https://v.vidxgo.co/'+record['imdbId'][2:]+'?content=trailer&player=false&info=0',
                             'label':'Trailer','kind':'embed'}
    return items


class CatalogFeatures:
    def __init__(self, context):
        self.c = context
        self.category_images = {}

    def primary(self):
        channels = self.c['state']()['channels']
        ready = [c for c in channels if c.get('status') == 'ready'] or channels
        return next((c for c in ready if 'streaming-community' in c['url']), ready[0] if ready else None)

    def unique(self, items):
        seen, result = set(), []
        for item in items:
            key = item.get('imdb') or self.c['normalize'](item['title']) + ':' + str(item.get('year',''))
            if key not in seen:
                seen.add(key); result.append(item)
        return result

    def archive(self, channel, page=1, query='', kind='', genre='', platform='', year='', sort='recent'):
        sort_name = {'popular':'Momento','rating':'Valutazione','top':'Valutazione','toprated':'Valutazione',
                     'year':'Data di uscita','recent':'Data di aggiornamento','title':'Nome'}.get(sort,'Data di aggiornamento')
        params = {'offset':(page-1)*30,'limit':30,'sort':sort_name,'count':1}
        if query:params['q']=query
        if kind:params['tipo']='Serie TV' if kind=='series' else 'Film'
        if genre:params['genere']=dict(GENRES).get(genre,genre)
        if platform:params['servizio']=dict(PLATFORMS).get(platform,platform)
        if year:params['anno']=year
        data,final,_ = self.c['fetch'](urljoin(channel['url'],'/api/v1/web/archive')+'?'+urlencode(params))
        payload=json.loads(data)
        if not isinstance(payload,dict) or not isinstance(payload.get('items'),list):
            raise ValueError('Il canale non ha restituito un catalogo valido.')
        items=[]
        for r in payload['items']:
            if not r.get('id') or not r.get('slug'):continue
            url=urljoin(channel['url'],f'/titles/{r.get("legacyId") or r["id"]}-{r["slug"]}-streaming')
            items.append({'id':str(r['id']),'title':r.get('title',''),'url':url,'poster':r.get('posterUrl') or r.get('tileUrl',''),
                          'backdrop':r.get('cleanUrl') or r.get('backdropUrl',''),'description':r.get('plot',''),
                          'year':r.get('year'),'kind':r.get('kind'),'genres':r.get('genres') or [],'rating':r.get('rating'),
                          'runtime':r.get('durationMin'),'imdb':r.get('imdbId'),'channel_id':channel['id'],'channel_name':channel['name']})
        total=payload.get('count')
        more=(page*30 < total) if isinstance(total,int) else len(items)>=30
        return {'items':items,'next_page':page+1 if more else None,'total':total}

    def home(self):
        channel = self.primary()
        if not channel:
            return {'hero': [], 'sections': [], 'platforms': [{'id':i,'name':n} for i,n in PLATFORMS], 'errors': []}
        markup, final, _ = self.c['fetch'](channel['url'])
        items, soup = self.c['parse_cards'](markup, final, channel)
        items = self.unique(items)
        sections = []
        for node in soup.select('.slider-title, .slider-section, section'):
            heading = node.select_one('.label, .section-title, h2, h3')
            if not heading:
                continue
            title = heading.get_text(' ', strip=True)
            if not title or len(title) > 80:
                continue
            cards, _ = self.c['parse_cards'](str(node), final, channel)
            # I metadati idratati appartengono alla pagina intera, non al solo blocco.
            all_by_url = {x['url']: x for x in items}
            cards = self.unique([all_by_url.get(x['url'], x) for x in cards])
            if not cards:
                continue
            top = 'top' in title.lower() and '10' in title
            sections.append({'id': 'top10' if top else 'source-'+str(len(sections)), 'title': title,
                             'items': cards[:10 if top else 24]})
        top = next((s for s in sections if s['id'] == 'top10'), None)
        if top:
            sections.remove(top); sections.insert(0, top)
        movie = [x for x in items if x.get('kind') in ('movie','film')]
        series = [x for x in items if x.get('kind') in ('series','tv')]
        if movie:
            sections.append({'id':'movies','title':'Film più popolari','items':sorted(movie,key=lambda x:float(x.get('popularity') or x.get('rating') or 0),reverse=True)[:24]})
        if series:
            sections.append({'id':'series','title':'Serie più popolari','items':sorted(series,key=lambda x:float(x.get('popularity') or x.get('rating') or 0),reverse=True)[:24]})
        history = self.c['state']().get('history', [])
        if isinstance(history, dict):
            history = list(history.values())
        progress = self.c['state']().get('progress', {})
        continuing = []
        for row in history:
            media = dict(row.get('media',row))
            media.update(progress.get(media.get('url'),{}))
            if media.get('position',0)>0 and not row.get('watched'):
                continuing.append(media)
        if continuing:
            sections.insert(0, {'id':'continue','title':'Continua a guardare','items':continuing[:20]})
        hero = [x for x in items if x.get('backdrop') and x.get('description')][:8]
        heading=soup.select_one('.info-wrap h2.title, .hero h1, .hero h2')
        if heading:
            first=next((x for x in items if self.c['normalize'](x['title'])==self.c['normalize'](heading.get_text(' ',strip=True))),None)
            if first:
                block=heading.find_parent(class_='info-wrap') or heading.parent
                title_image=block.select_one('img.img-fluid[title], img[title]')
                if title_image and title_image.get('src'):
                    first['title_image']=urljoin(final,title_image['src'])
                hero=[first]+[x for x in hero if x['url']!=first['url']]
                hero=hero[:8]
        if not hero:
            hero = items[:8]
        return {'hero':hero,'sections':sections,'platforms':[{'id':i,'name':n} for i,n in PLATFORMS],
                'errors':[], 'source':channel['name'], 'categories':self.categories(items)}

    def categories(self, items, kind='movie'):
        result = []
        for gid,name in EDITORIAL:
            if gid=='cinema':
                item=next((x for x in items if x.get('in_cinema')),None)
            elif gid=='superheroes':
                item=next((x for x in items if any(t in x['title'].lower() for t in ('spider','batman','superman','marvel','avengers'))),None)
            elif gid=='christmas':
                item=next((x for x in items if any(t in x['title'].lower() for t in ('natale','christmas'))),None)
            elif gid=='disney':
                item=next((x for x in items if any('disney' in p.lower() for p in x.get('platforms',[]))),None)
            else:item=next(iter(items),None)
            result.append({'id':gid,'name':name,'image':(item or {}).get('backdrop') or (item or {}).get('poster','')})
        for gid, name in GENRES:
            item = next((x for x in items if any(gid in self.c['normalize'](g) for g in x.get('genres',[]))), None)
            result.append({'id':gid,'name':name,'image':(item or {}).get('backdrop') or (item or {}).get('poster','')})
        missing=[r for r in result if not r['image']]
        channel=self.primary()
        if missing and channel and 'streaming-community' in channel['url']:
            def illustration(row):
                cache_key=(kind,row['id'])
                if cache_key in self.category_images:return self.category_images[cache_key]
                params={'offset':0,'limit':1,'tipo':'Serie TV' if kind=='series' else 'Film','sort':'Data di aggiornamento'}
                if row['id']=='christmas':params['q']='Natale'
                elif row['id']=='superheroes':params['q']='supereroi'
                elif row['id']=='disney':params['servizio']='Disney+'
                elif row['id'] in dict(GENRES):params['genere']=dict(GENRES)[row['id']]
                try:
                    data,_,_=self.c['fetch'](urljoin(channel['url'],'/api/v1/web/archive')+'?'+urlencode(params),ttl=86400)
                    matches=json.loads(data).get('items',[])
                    first=matches[0] if matches else {}
                    image=first.get('cleanUrl') or first.get('backdropUrl') or first.get('posterUrl') or ''
                    if image:self.category_images[cache_key]=image
                    return image
                except Exception:return ''
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=3)
            futures={pool.submit(illustration,row):row for row in missing}
            complete,_=concurrent.futures.wait(futures,timeout=3)
            for future in complete:futures[future]['image']=future.result()
            pool.shutdown(wait=False,cancel_futures=True)
        return result

    def discover(self, args):
        channel = self.primary()
        if not channel:
            return {'items': [], 'next_page':None, 'categories':self.categories([])}
        page = max(1,min(500,int(args.get('page',1))))
        genre, kind, platform = args.get('genre',''), args.get('kind','movie'), args.get('platform','')
        if 'streaming-community' in channel['url']:
            category=args.get('category') or (genre if genre in dict(EDITORIAL) else '')
            if category:genre=''
            order=args.get('sort','recent')
            query=''
            if category=='popular':order='popular'
            elif category=='toprated':order='rating'
            elif category=='christmas':query='Natale'
            elif category=='superheroes':query='supereroi'
            elif category=='disney':platform='disney'
            if category=='cinema':
                markup,final,_=self.c['fetch'](channel['url'])
                cards,_=self.c['parse_cards'](markup,final,channel)
                result={'items':[x for x in self.unique(cards) if x.get('in_cinema') and x.get('kind')==kind],'next_page':None}
            else:
                result=self.archive(channel,page,query=query,kind=kind,genre=genre,platform=platform,year=args.get('year',''),sort=order)
            result.update(categories=self.categories(result['items'],kind),platforms=[{'id':i,'name':n} for i,n in PLATFORMS])
            return result
        params = {'page':page}
        if kind in ('movie','series'):
            params['type'] = kind
        if genre and genre in dict(GENRES):
            params['genre'] = dict(GENRES)[genre]
        if args.get('year','').isdigit():
            params['year'] = args['year']
        target = urljoin(channel['url'],'/archivio') + '?' + urlencode(params)
        if self.c['channel_mode'](channel) != 'next':
            result = self.c['catalog'](channel, page)
            items = result['items']; next_page = result['next_page']
        else:
            markup, final, _ = self.c['fetch'](target)
            items, _ = self.c['parse_cards'](markup, final, channel)
            next_page = page+1 if len(items)>=30 else None
        # Alcuni siti ignorano filtri query sconosciuti: applicare sempre anche filtro locale.
        items = [x for x in items if (kind=='series') == (x.get('kind') in ('series','tv'))]
        if genre:
            label = self.c['normalize'](dict(GENRES).get(genre,genre))
            items = [x for x in items if any(label in self.c['normalize'](g) for g in x.get('genres',[]))]
        if platform:
            labels = {'prime':['amazon','prime'], 'disney':['disney'], 'apple':['apple'], 'now':['now','sky'],
                      'paramount':['paramount'],'netflix':['netflix'],'crunchyroll':['crunchyroll']}.get(platform,[platform])
            items = [x for x in items if any(any(label in n.casefold() for label in labels) for n in x.get('platforms',[]))]
        if args.get('year'):
            items = [x for x in items if str(x.get('year'))==args['year']]
        order = args.get('sort','popular')
        if order in ('rating','top','toprated'):
            items.sort(key=lambda x:float(x.get('rating') or 0),reverse=True)
        elif order in ('year','recent'):
            items.sort(key=lambda x:int(x.get('year') or 0),reverse=True)
        elif order=='title':
            items.sort(key=lambda x:x['title'])
        else:
            items.sort(key=lambda x:float(x.get('popularity') or 0),reverse=True)
        return {'items':self.unique(items),'next_page':next_page,'categories':self.categories(items),
                'platforms':[{'id':i,'name':n} for i,n in PLATFORMS], 'scope':'Filtri sui risultati restituiti dal canale selezionato.'}

    def enrich_detail(self, result, markup, base, channel):
        records = payload_records(markup, self.c['hydration'])
        item = next((x for x in records if self.c['normalize'](x['title'])==self.c['normalize'](result['title'])), None)
        if not item:
            return result
        result.update(description=item.get('plot') or result.get('description',''), year=item.get('year') or '',
                      genres=item.get('genres') or [], rating=item.get('rating'), runtime=item.get('durationMin'),
                      backdrop=item.get('backdropUrl') or result.get('poster'), poster=item.get('posterUrl') or result.get('poster'),
                      tagline=item.get('tagline'), director=item.get('director'), platforms=item.get('networks') or [],
                      release_date=item.get('releaseDate'), country=item.get('country'), original_language=item.get('originalLanguage'),
                      title_image=item.get('logoUrl'),
                      production_companies=item.get('productionCompanies') or [], collection=item.get('collection'),
                      galleries=[urljoin(base,p) for p in (item.get('backdropPaths') or []) if isinstance(p,str)],
                      imdb=item.get('imdbId'), budget=(item.get('tmdbExtra') or {}).get('budget'), revenue=(item.get('tmdbExtra') or {}).get('revenue'))
        image_base = (item.get('posterUrl') or item.get('backdropUrl') or '').split('/t/p/')[0]
        paths=[]
        for key in ('backdropClean','backdropText','posterPaths'):
            value=item.get(key) or []
            paths.extend([value] if isinstance(value,str) else value if isinstance(value,list) else [])
        if '/t/p/' in (item.get('posterUrl') or item.get('backdropUrl') or ''):
            result['galleries'] = list(dict.fromkeys(image_base+'/t/p/w1280'+p for p in paths if isinstance(p,str) and p.startswith('/')))[:20]
        cast = item.get('cast') or ''
        if isinstance(cast, str):
            cast = [n.strip() for n in cast.split(',') if n.strip()]
        result['cast'] = [{'name':n.split(' (')[0], 'role':n.split(' (',1)[1].rstrip(')') if ' (' in n else '', 'image':''}
                          for n in cast[:30] if isinstance(n,str)]
        def photo(actor):
            try:
                text,_,_=self.c['fetch']('https://api.tvmaze.com/search/people?'+urlencode({'q':actor['name']}),ttl=86400)
                matches=json.loads(text)
                person=next((x['person'] for x in matches if self.c['normalize'](x['person']['name'])==self.c['normalize'](actor['name'])),None)
                return (person.get('image') or {}).get('medium','') if person else ''
            except Exception:
                return ''
        if result['cast']:
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=3)
            futures={pool.submit(photo,actor):actor for actor in result['cast'][:8]}
            complete,_=concurrent.futures.wait(futures,timeout=2.5)
            for future in complete:
                futures[future]['image']=future.result()
            pool.shutdown(wait=False,cancel_futures=True)
            if any(a['image'] for a in result['cast']):
                result['cast_source']={'name':'TVmaze','url':'https://www.tvmaze.com/api','license':'CC BY-SA'}
        soup = BeautifulSoup(markup,'html.parser')
        trailer = next((x.get('src') for x in soup.select('iframe[src]') if 'content=trailer' in x['src']), None)
        result['trailer'] = {'url':urljoin(base,trailer),'label':'Trailer','kind':'embed'} if trailer else None
        similar_titles = {self.c['normalize'](x.get('title','')) for x in item.get('similar',[]) if isinstance(x,dict)}
        cards, _ = self.c['parse_cards'](markup,base,channel)
        result['similar'] = [x for x in self.unique(cards) if self.c['normalize'](x['title']) in similar_titles][:18]
        if not result['similar']:
            result['similar'] = [x for x in self.unique(cards) if x['url']!=result['url']][:12]
        result['seasons'] = sorted({int(re.search(r'S(\d+)',e['label']).group(1)) for e in result.get('episodes',[]) if re.search(r'S(\d+)',e['label'])})
        return result

    def calendar(self, date):
        day = datetime.date.fromisoformat(date or datetime.date.today().isoformat())
        text, _, _ = self.c['fetch']('https://api.tvmaze.com/schedule/web?' + urlencode({'date':day.isoformat()}), ttl=1800)
        episodes = json.loads(text)
        result = []
        for ep in episodes[:250]:
            show = ep.get('_embedded',{}).get('show') or ep.get('show') or {}
            result.append({'id':ep.get('id'),'show_id':show.get('id'),'title':show.get('name',''), 'episode':ep.get('name',''),
                           'season':ep.get('season'),'number':ep.get('number'),'time':ep.get('airtime',''),
                           'date':ep.get('airdate'),'airstamp':ep.get('airstamp'),'image':(ep.get('image') or show.get('image') or {}).get('medium',''),
                           'network':(show.get('webChannel') or show.get('network') or {}).get('name','')})
        return {'date':day.isoformat(),'items':result,'source':'TVmaze','source_url':'https://www.tvmaze.com/api'}

    def calendar_search(self, query):
        if len(query.strip())<2:
            return {'items':[],'source':'TVmaze'}
        text,_,_=self.c['fetch']('https://api.tvmaze.com/search/shows?'+urlencode({'q':query[:150]}),ttl=1800)
        items=[]
        for match in json.loads(text)[:25]:
            show=match.get('show',{})
            items.append({'id':show.get('id'),'title':show.get('name',''),'image':(show.get('image') or {}).get('medium',''),
                          'url':show.get('url',''),'imdb':(show.get('externals') or {}).get('imdb')})
        return {'items':items,'source':'TVmaze','source_url':'https://www.tvmaze.com/api'}
