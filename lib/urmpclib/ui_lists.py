import re
import urwid
import mpd

import signals
import util
import configuration
from configuration import config

class IOWalker(urwid.ListWalker):
	def __init__(self):
		self.previous_search = None
		self.focus = 0
		self.items = []
		self._reload()

	def get_focus(self):
		return self._get_at_pos(self.focus)
	def set_focus(self, focus):
		self.focus = focus
		self._modified()

	def get_next(self, pos):
		if pos is None: return None, None
		return self._get_at_pos(pos + 1)
	def get_prev(self, pos):
		if pos is None: return None, None
		return self._get_at_pos(pos - 1)

	def _get_raw(self, pos):
		if pos < 0:
			return None
		try:
			return self.items[pos]
		except IndexError as e:
			return None
		
	def _get_at_pos(self, pos):
		item = self._get_raw(pos)
		if item is None:
			return None, None
		if id(item) not in self._formatcache:
			self._formatcache[id(item)] = self._format(item)
		return self._formatcache[id(item)], pos

	def _reload(self):
		"""Grab items from datastore and apply any changes, attempting to
		preserve focus as intelligently as possible."""
		self._formatcache = {}
		focus = self.focus
		item = self._get_raw(focus)
		self.items[:] = self._get_items()
		count = len(self.items)
		try:
			if focus >= count or item != self.items[focus]:
				self.focus = self.items.index(item)
		except ValueError as e:
			if focus < count:
				self.focus = focus
			elif count > 0:
				self.focus = count - 1
			else:
				self.focus = 0
		self._modified()
		return True

	def init_search(self):
		searchbox = util.SearchLine(self.submit_search)
		signals.emit('user_interactive', searchbox)

	def submit_search(self, input=None):
		signals.emit('user_interactive_end')

		if input is None:
			if self.previous_search is None:
				return
			input = self.previous_search

		try:
			results = sorted(self._search_query(input))
		except re.error as e:
			signals.emit('user_notification', 'Invalid regexp: %s' % input)
			return

		self.previous_search = input

		next = None
		try:
			next = [x for x in results if x > self.focus][0]
		except IndexError as e:
			if len(results) > 0:
				if results[0] == self.focus:
					return # Only match
				next = results[0]

		if next is None:
			signals.emit('user_notification', 'Not found: %s' % input)
			return
		self.set_focus(next)

	# Override these.
	def _get_items(self):
		"""Returns a fresh copy of the items from the datastore."""
		return []
	def _format(self, item):
		"""Returns a widget suitable for display."""
		return item
	def _search_query(self, text): # In many cases this doesn't need overriding.
		"""Returns indexes of items containing text."""
		pattern = re.compile(text, re.IGNORECASE)
		output = []
		for i in range(len(self.items)):
			if pattern.search(str(self.items[i])):
				output.append(i)
		return output

@signals.sends_signal('change')
class ArtistWalker(IOWalker):
	def __init__(self, mpc):
		self.mpc = mpc
		ignore_leading_the = config.format.library.ignore_leading_the
		if configuration.truthiness(ignore_leading_the):
			def sort(artist):
				artist = artist.lower()
				if artist.startswith('the '):
					return artist[4:]
				return artist
			self._sort = sort
		else:
			self._sort = lambda artist: artist.lower()
		super(ArtistWalker, self).__init__()
		signals.listen('idle_database', self._reload)

	def _get_items(self):
		return sorted(self.mpc.list('artist'), key=self._sort)

	def _format(self, item):
		if item == '':
			item = config.format.empty_tag
		item = urwid.Text(item)
		item.set_wrap_mode('clip')
		item = urwid.AttrMap(item,
		                     {None: 'library.column'},
		                     {None: 'library.column.focus'})
		return item

	def set_focus(self, focus):
		super(ArtistWalker, self).set_focus(focus)
		urwid.emit_signal(self, 'change', self.items[focus])

	def play_current(self):
		song_id = self.queue_current()
		if song_id is not None:
			self.mpc.playid(song_id)
	def queue_current(self):
		item = super(ArtistWalker, self)._get_raw(self.focus)
		if item is None:
			return None
		song_id = None
		for song in self.mpc.find('artist', item):
			sid = self.mpc.addid(song['file'])
			if song_id is None:
				song_id = sid
		signals.emit('user_notification', 'Adding artist "%s"' % item)
		return song_id

@signals.sends_signal('change')
class AlbumWalker(IOWalker):
	def __init__(self, mpc, artist):
		self.mpc = mpc
		self.artist = artist
		super(AlbumWalker, self).__init__()

	def _get_items(self):
		return sorted(self.mpc.list('album', 'artist', self.artist))

	def _format(self, item):
		if item == '':
			item = config.format.empty_tag
		item = urwid.Text(item)
		item.set_wrap_mode('clip')
		item = urwid.AttrMap(item,
		                     {None: 'library.column'},
		                     {None: 'library.column.focus'})
		return item

	def set_focus(self, focus):
		super(AlbumWalker, self).set_focus(focus)
		urwid.emit_signal(self, 'change', (self.artist, self.items[focus]))

	def change_artist(self, value):
		self.artist = value
		self._reload()
		self.set_focus(self.focus)

	def play_current(self):
		song_id = self.queue_current()
		if song_id is not None:
			self.mpc.playid(song_id)
	def queue_current(self):
		item = super(AlbumWalker, self)._get_raw(self.focus)
		if item is None:
			return None
		song_id = None
		for song in self.mpc.find('artist', self.artist, 'album', item):
			sid = self.mpc.addid(song['file'])
			if song_id is None:
				song_id = sid
		signals.emit('user_notification', 'Adding album "%s" - %s' % (item, self.artist))
		return song_id


class TrackWalker(IOWalker):
	def __init__(self, mpc, artist, album):
		self.mpc = mpc
		self.artist = artist
		self.album = album
		super(TrackWalker, self).__init__()

	def _get_items(self):
		#TODO: Make sure this sorts like it should.
		return self.mpc.find('artist', self.artist, 'album', self.album)

	def _format(self, item):
		try:
			text = item['title']
		except KeyError as e:
			text = item['file']
		if text == '':
			text = config.format.empty_tag
		text = urwid.Text(text)
		text.set_wrap_mode('clip')
		text = urwid.AttrMap(text,
		                     {None: 'library.column'},
		                     {None: 'library.column.focus'})
		return text

	def change_album(self, artist_album):
		self.artist, self.album = artist_album
		self._reload()

	def play_current(self):
		song_id = self.queue_current()
		if song_id is not None:
			self.mpc.playid(song_id)
	def queue_current(self):
		item = super(TrackWalker, self)._get_raw(self.focus)
		if item is None:
			return None
		song = self.mpc.find('file', item['file'])
		if song == []:
			return None
		song = song[0]
		song_id = self.mpc.addid(song['file'])

		#TODO: Do this like self._format, this is ugly.
		try:
			name = item['title']
		except KeyError as e:
			name = item['file']
		try:
			artist = item['artist']
		except KeyError as e:
			artist = config.format.empty_tag
		
		signals.emit('user_notification', 'Adding "%s" by %s' % (name, artist))
		return song_id

class TreeList(urwid.ListBox):
	def __init__(self, *args, **kwargs):
		actionmap = {
			'left': lambda s: self._keypress_remap(s, 'left'),
			'right': lambda s: self._keypress_remap(s, 'right'),
			'page up': lambda s: self._keypress_remap(s, 'page up'),
			'page down': lambda s: self._keypress_remap(s, 'page down'),
			'up': self._keypress_up,
			'down': lambda s: self._keypress_down(s),
			'home': lambda _: self._scroll_top(),
			'end': lambda _: self._scroll_bottom(),
			'search': lambda _: self.body.init_search(),
			'search_again': lambda _: self.body.submit_search(),
		}
		self.keymap = configuration.KeyMapper(actionmap, config.keymap.list)
		return super(TreeList, self).__init__(*args, **kwargs)

	def keypress(self, size, key):
		if key in self.keymap:
			return self.keymap(size, key)
		else:
			return super(TreeList, self).keypress(size, key)

	def _keypress_up(self, size):
		middle, top, bottom = self.calculate_visible(size, True)
		if middle is not None and middle[0] == 0:
			return super(TreeList, self)._keypress_up(size)
		w, pos = self.body.get_focus()
		w, pos = self.body.get_prev(pos)
		if w and pos is not None:
			self.set_focus(pos)

	def _keypress_down(self, size):
		middle, top, bottom = self.calculate_visible(size, True)
		if middle is not None and middle[0] + 1 == size[1]:
			return super(TreeList, self)._keypress_down(size)
		w, pos = self.body.get_focus()
		w, pos = self.body.get_next(pos)
		if w and pos is not None:
			self.set_focus(pos)

	def _keypress_remap(self, size, key):
		return super(TreeList, self).keypress(size, key)

	def _scroll_top(self):
		self.set_focus(0)
	def _scroll_bottom(self):
		self.set_focus(len(self.body.items)-1)


class PlayableList(TreeList):
	def __init__(self, *args, **kwargs):
		super(PlayableList, self).__init__(*args, **kwargs)
		actionmap = {
			'play': lambda _: self.body.play_current(),
			'queue': lambda _: self.body.queue_current(),
		}
		self.keymap.update(actionmap, config.keymap.playable_list)

class NowPlayingWalker(IOWalker):
	def __init__(self, mpc):
		self.mpc = mpc
		super(NowPlayingWalker, self).__init__()
		signals.listen('idle_playlist', self._reload)

	def _get_items(self):
		return self.mpc.playlistinfo()

	def _format(self, item):
		if 'artist' not in item: item['artist'] = config.format.empty_tag
		if 'album' not in item: item['album'] = config.format.empty_tag
		if 'title' not in item: item['title'] = config.format.empty_tag

		time = str(util.timedelta(seconds=int(item['time'])))
		time = urwid.AttrMap(urwid.Text(time, wrap='clip', align='left'), 'time')
		time = ('fixed', 6, time)

		artist = urwid.AttrMap(urwid.Text(item['artist'], wrap='clip'), 'artist')
		artist = ('weight', 1.0, artist)

		title = urwid.AttrMap(urwid.Text(item['title'], wrap='clip'), 'title')
		title = ('weight', 1.5, title)

		album = urwid.AttrMap(urwid.Text(item['album'], wrap='clip', align='right'), 'album')
		album = ('weight', 1.0, album)

		item = urwid.Columns((time, artist, title, album))

		return urwid.AttrMap(
			item,
			{
				'time': 'playlist.time',
				'artist': 'playlist.artist',
				'title': 'playlist.title',
				'album': 'playlist.album',
			},
			{
				'time': 'playlist.time.focus',
				'artist': 'playlist.artist.focus',
				'title': 'playlist.title.focus',
				'album': 'playlist.album.focus',
			},
		)

	def set_focus(self, focus):
		super(NowPlayingWalker, self).set_focus(focus)
		if focus in self.items:
			urwid.emit_signal(self, 'change', self.items[focus])

	def play_current(self):
		item = super(NowPlayingWalker, self)._get_raw(self.focus)
		if item is None:
			return
		self.mpc.playid(item['id'])

	def delete_current(self):
		item = super(NowPlayingWalker, self)._get_raw(self.focus)
		if item is None:
			return
		try:
			self.mpc.deleteid(item['id'])
		except mpd.CommandError as e:
			self._reload()

	def swap_down(self):
		f = self.focus
		this, below = self._get_raw(f), self._get_raw(f+1)
		if this is None or below is None:
			return
		this, below = this['id'], below['id']
		self.items[f], self.items[f+1] = self.items[f+1], self.items[f]
		self.focus += 1
		self.mpc.swapid(this, below)

	def swap_up(self):
		f = self.focus
		this, above = self._get_raw(f), self._get_raw(f-1)
		if this is None or above is None:
			return
		this, above = this['id'], above['id']
		self.items[f], self.items[f-1] = self.items[f-1], self.items[f]
		self.focus -= 1
		self.mpc.swapid(this, above)

	def focus_playing(self):
		status = self.mpc.status()
		if 'song' in status and status['state'] != 'stop':
			self.set_focus(int(status['song']))

class HelpPanelWalker(IOWalker):
	def _get_items(self):
		# Get (section, action) combinations for _format to use.
		out = []
		for section in config.keymap.keys():
			#FIXME: Forcing __getitem__ because I failed to override all dict
			#       magic methods in configuration.ConfigSection.
			out.append((section, None))
			for action in config.keymap[section].keys():
				out.append((section, action))
		return sorted(out)

	def _format(self, item):
		section, action = item
		if action is None:
			return urwid.Text(('help.section', '\n%s:' % section))

		key = config.keymap[section][action]
		if key == ' ': key = 'space' # Everything but this is readable...

		actionline = ['    ', ('help.action', '%s:' % action),
		              ' ', ('help.key', str(key))]
		return urwid.Text(actionline)

