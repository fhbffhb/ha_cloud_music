import uuid, time, logging, os, hashlib, aiohttp
from urllib.parse import quote
from homeassistant.helpers.network import get_url
from .http_api import http_get, http_cookie
from .models.music_info import MusicInfo, MusicSource
from homeassistant.helpers.storage import STORAGE_DIR
from homeassistant.util.json import load_json, save_json

from .browse_media import (
    async_browse_media, 
    async_play_media, 
    async_media_previous_track, 
    async_media_next_track
)

def md5(data):
    return hashlib.md5(data.encode('utf-8')).hexdigest()

_LOGGER = logging.getLogger(__name__)

class CloudMusic():

    def __init__(self, hass, url) -> None:
        self.hass = hass
        self.api_url = url.strip('/')

        # 媒体资源
        self.async_browse_media = async_browse_media
        self.async_play_media = async_play_media
        self.async_media_previous_track = async_media_previous_track
        self.async_media_next_track = async_media_next_track

        self.userinfo = {}
        # 读取用户信息
        self.userinfo_filepath = self.get_storage_dir('cloud_music.userinfo')
        if os.path.exists(self.userinfo_filepath):
            self.userinfo = load_json(self.userinfo_filepath)

    def get_storage_dir(self, file_name):
        return os.path.abspath(f'{STORAGE_DIR}/{file_name}')

    def netease_image_url(self, url, size=200):
        return f'{url}?param={size}y{size}'

    # 登录
    async def login(self, username, password):
        login_url = f'{self.api_url}/login'
        if username.count('@') > 0:
            login_url = login_url + '?email='
        else:
            login_url = login_url + '/cellphone?phone='

        data = await http_cookie(login_url + f'{quote(username)}&md5_password={md5(password)}')
        _LOGGER.debug(data)
        res_data = data.get('data', {})
        # 登录成功
        if res_data.get('code') == 200:
            # 写入cookie
            uid = res_data['account']['id']
            cookie = data.get('cookie')
            self.userinfo = {
                'uid': uid,
                'cookie': cookie
            }
            save_json(self.userinfo_filepath, self.userinfo)
            return res_data
        else:
            print(res_data)

    # 获取播放链接
    def get_play_url(self, id, song, singer, source):
        base_url = get_url(self.hass, prefer_external=True)
        if singer is None:
            singer = ''
        return f'{base_url}/cloud_music/url?id={id}&song={quote(song)}&singer={quote(singer)}&source={source}'

    # 网易云音乐接口
    async def netease_cloud_music(self, url):
        return await http_get(self.api_url + url, self.userinfo.get('cookie', {}))

    # 获取音乐链接
    async def song_url(self, id):
        res = await self.netease_cloud_music(f'/song/url/v1?id={id}&level=standard')
        data = res['data'][0]
        url = data['url']
        # 0：免费
        # 1：收费
        fee = 0 if data['freeTrialInfo'] is None else 1
        return url, fee

    # 获取云盘音乐链接
    async def cloud_song_url(self, id):
        res = await self.netease_cloud_music(f'/user/cloud')
        filter_list = list(filter(lambda x:x['simpleSong']['id'] == id, res['data']))
        if len(filter_list) > 0:
            songId = filter_list[0]['songId']
            url, fee = await self.song_url(songId)
            return url

    # 获取歌单列表
    async def async_get_playlist(self, playlist_id):
        res = await self.netease_cloud_music(f'/playlist/track/all?id={playlist_id}')

        def format_playlist(item):
            id = item['id']
            song = item['name']
            singer = item['ar'][0].get('name', '')
            album = item['al']['name']
            duration = item['dt']
            url = self.get_play_url(id, song, singer, MusicSource.PLAYLIST.value)
            picUrl = item['al'].get('picUrl', 'https://p2.music.126.net/fL9ORyu0e777lppGU3D89A==/109951167206009876.jpg')
            music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.PLAYLIST.value)
            return music_info

        return list(map(format_playlist, res['songs']))

    # 获取电台列表
    async def async_get_djradio(self, rid):
        res = await self.netease_cloud_music(f'/dj/program?rid={rid}&limit=200')

        def format_playlist(item):
            mainSong = item['mainSong']
            id = mainSong['id']
            song = mainSong['name']
            singer = mainSong['artists'][0]['name']
            album = item['dj']['brand']
            duration = mainSong['duration']
            url = self.get_play_url(id, song, singer, MusicSource.DJRADIO.value)
            picUrl = item['coverUrl']
            music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.DJRADIO.value)
            return music_info
        
        return list(map(format_playlist, res['programs']))

    # 获取歌手列表
    async def async_get_artists(self, aid):
        res = await self.netease_cloud_music(f'/artists?id={aid}')

        def format_playlist(item):
            id = item['id']
            song = item['name']
            singer = item['ar'][0]['name']
            album = item['al']['name']
            duration = item['dt']
            url = self.get_play_url(id, song, singer, MusicSource.ARTISTS.value)
            picUrl = res['artist']['picUrl']
            music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.ARTISTS.value)
            return music_info
        
        return list(map(format_playlist, res['hotSongs']))

    # 获取云盘音乐
    async def async_get_cloud(self):
        res = await self.netease_cloud_music('/user/cloud')
        def format_playlist(item):
            id = item['songId']
            song = ''
            singer = ''
            duration = ''            
            album = ''
            picUrl = 'http://p3.music.126.net/ik8RFcDiRNSV2wvmTnrcbA==/3435973851857038.jpg'

            simpleSong = item.get('simpleSong')
            if simpleSong is not None:
                song = simpleSong.get("name")
                duration = simpleSong.get("dt")
                al = simpleSong.get('al')
                if al is not None:
                    picUrl = al.get('picUrl')
                    album = al.get('name')
                ar = simpleSong.get('ar')
                if ar is not None and len(ar) > 0:
                    singer = ar[0].get('name', '')

            if singer is None:
                singer = ''

            url = self.get_play_url(id, song, singer, MusicSource.CLOUD.value)
            music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.CLOUD.value)
            return music_info

        return list(map(format_playlist, res['data']))

    # 获取每日推荐歌曲
    async def async_get_dailySongs(self):
        res = await self.netease_cloud_music('/recommend/songs')
        def format_playlist(item):
            id = item['id']
            song = item['name']
            singer = item['ar'][0]['name']
            album = item['al']['name'] 
            duration = item['dt']
            url = self.get_play_url(id, song, singer, MusicSource.PLAYLIST.value)
            picUrl = item['al'].get('picUrl', 'https://p2.music.126.net/fL9ORyu0e777lppGU3D89A==/109951167206009876.jpg')
            music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.PLAYLIST.value)
            return music_info

        return list(map(format_playlist, res['data']['dailySongs']))

    # 乐听头条
    async def async_ting_playlist(self, catalog_id):
        
        now = int(time.time())
        if hasattr(self, 'letingtoutiao') == False:
            uid = uuid.uuid4().hex
            self.letingtoutiao = {
                'time': now,
                'headers': {"uid": uid, "logid": uid, "token": ''}
            }

        headers = self.letingtoutiao['headers']
        async with aiohttp.ClientSession() as session:
            # 获取token
            if headers['token'] == '' or now > self.letingtoutiao['time']:
                async with session.get('https://app.leting.io/app/auth?uid=' + 
                    uid + '&appid=a435325b8662a4098f615a7d067fe7b8&ts=1628297581496&sign=4149682cf40c2bf2efcec8155c48b627&v=v9&channel=huawei', 
                    headers=headers) as res:
                    r = await res.json()
                    token = r['data']['token']
                    headers['token'] = token
                    # 保存时间（10分钟重新获取token）
                    self.letingtoutiao['time'] = now + 60 * 10
                    self.letingtoutiao['headers']['token'] = token

            # 获取播放列表
            async with session.get('https://app.leting.io/app/url/channel?catalog_id=' + 
                catalog_id + '&size=100&distinct=1&v=v8&channel=xiaomi', headers=headers) as res:
                r = await res.json()

                def format_playlist(item):
                    id = item['sid']
                    song = item['title']
                    singer = item['source']
                    album = item['catalog_name']
                    duration = item['duration']
                    url = item['audio']
                    picUrl = item['source_icon']
                    music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.URL.value)
                    return music_info

                return list(map(format_playlist, r['data']['data']))

    # 喜马拉雅
    async def async_xmly_playlist(self, id, page=1, size=50, asc=1):
        if page < 1:
            page = 1
        isAsc = 'true' if asc != 1 else 'false'
        url = f'https://mobile.ximalaya.com/mobile/v1/album/track?albumId={id}&isAsc={isAsc}&pageId={page}&pageSize={size}'
        result = await http_get(url)
        if result['ret'] == 0:
            _list = result['data']['list']
            _totalCount = result['data']['totalCount']
            if len(_list) > 0:
                # 获取专辑名称
                trackId = _list[0]['trackId']
                url = f'http://mobile.ximalaya.com/v1/track/baseInfo?trackId={trackId}'
                album_result = await http_get(url)
                # 格式化列表
                def format_playlist(item):
                    id = item['trackId']
                    song = item['title']
                    singer = item['nickname']
                    album = album_result['albumTitle']
                    duration = item['duration']
                    url = item['playUrl64']
                    picUrl = item['coverLarge']
                    music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.XIMALAYA.value)
                    return music_info

                return list(map(format_playlist, _list))

    # FM
    async def async_fm_playlist(self, id, page=1, size=100):
        result = await http_get(f'https://rapi.qingting.fm/categories/{id}/channels?with_total=true&page={page}&pagesize={size}')
        data = result['Data']
        # 格式化列表
        def format_playlist(item):
            id = item['content_id']
            song = item['title']
            album = item['categories'][0]['title']
            singer = album
            duration = item['audience_count']
            url = f'http://lhttp.qingting.fm/live/{id}/64k.mp3'
            picUrl = item['cover']

            nowplaying = item.get('nowplaying')
            if nowplaying is not None:
                singer = nowplaying.get('title', song)

            music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.URL.value)
            return music_info

        return list(map(format_playlist, data['items']))

    # 音乐搜索
    async def async_search_song(self, name):
        ha_music_source = self.hass.data.get('ha_music_source')
        if ha_music_source is not None:
            music_list = await ha_music_source.async_search_all(name)
            # 格式化列表
            def format_playlist(item):
                id = item['id']
                song = item['song']
                album = item['album']
                singer = item['singer']
                duration = 0
                url = item['url']
                picUrl = self.netease_image_url('http://p1.music.126.net/6nuYK0CVBFE3aslWtsmCkQ==/109951165472872790.jpg')

                music_info = MusicInfo(id, song, singer, album, duration, url, picUrl, MusicSource.URL.value)
                return music_info

            return list(map(format_playlist, music_list))

    # 电台
    async def async_search_djradio(self, name):
        _list = []
        res = await self.netease_cloud_music(f'/search?keywords={name}&type=1009')
        if res['code'] == 200:
            _list = list(map(lambda item: {
                "id": item['id'],
                "name": item['name'],
                "cover": item['picUrl'],
                "intro": item['dj']['signature'],
                "creator": item['dj']['nickname'],
                "source": MusicSource.DJRADIO.value
            }, res['result']['djRadios']))
        return _list

    # 喜马拉雅
    async def async_search_xmly(self, name):
        _list = []
        url = f'https://m.ximalaya.com/m-revision/page/search?kw={name}&core=all&page=1&rows=5'
        res = await http_get(url)
        if res['ret'] == 0:
            result = res['data']['albumViews']
            if result['total'] > 0:
                _list = list(map(lambda item: {
                    "id": item['albumInfo']['id'],
                    "name": item['albumInfo']['title'],
                    "cover": item['albumInfo'].get('cover_path', 'https://imagev2.xmcdn.com/group79/M02/77/6C/wKgPEF6masWTCICAAAA7qPQDtNY545.jpg!strip=1&quality=7&magick=webp&op_type=5&upload_type=cover&name=web_large&device_type=ios'),
                    "intro": item['albumInfo']['intro'],
                    "creator": item['albumInfo']['nickname'],
                    "source": MusicSource.XIMALAYA.value
                }, result['albums']))
        return _list

    # 歌单
    async def async_search_playlist(self, name):
        _list = []
        res = await self.netease_cloud_music(f'/search?keywords={name}&type=1000')
        if res['code'] == 200:
            _list = list(map(lambda item: {
                "id": item['id'],
                "name": item['name'],
                "cover": item['coverImgUrl'],
                "intro": item['description'],
                "creator": item['creator']['nickname'],
                "source": MusicSource.PLAYLIST.value
            }, res['result']['playlists']))
        return _list

    # 歌手
    async def async_search_singer(self, name):
        _list = []
        res = await self.netease_cloud_music(f'/search?keywords={name}&type=100')
        if res['code'] == 200:
            _list = list(map(lambda item: {
                "id": item['id'],
                "name": item['name'],
                "cover": item['picUrl'],
                "intro": '、'.join(item['alias']),
                "creator": item['name'],
                "source": MusicSource.ARTISTS.value
            }, res['result']['artists']))
        return _list