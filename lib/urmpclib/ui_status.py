# -*- coding: utf-8 -*-
import urwid

import signals
import util

# File "/usr/lib/python2.7/site-packages/urwid/util.py", line 431, in __init__
#	raise AttributeError, "Class has same name as one of its super classes"
# lol wut's a namespace, guys? PROTIP: metaclasses are usually overengineering.
# And so we can't just name it ProgressBar...
class ProgressBar_(urwid.ProgressBar):
	"""Because urwid.ProgressBar can't do anything but "%s %" centered.
	If you're watching, Ian, this is one of the little things on my wishlist."""
	def render(self, size, focus=False):
		"""
		Render the progress bar.
		"""
		(maxcol,) = size

		txt = self.get_text()
		c = txt.render((maxcol,))

		cf = float( self.current ) * maxcol / self.done
		ccol = int( cf )
		cs = 0
		if self.satt is not None:
			cs = int((cf - ccol) * 8)
		if ccol < 0 or (ccol == 0 and cs == 0):
			c._attr = [[(self.normal,maxcol)]]
		elif ccol >= maxcol:
			c._attr = [[(self.complete,maxcol)]]
		elif cs and c._text[0][ccol] == " ":
			t = c._text[0]
			cenc = self.eighths[cs].encode("utf-8")
			c._text[0] = t[:ccol]+cenc+t[ccol+1:]
			a = []
			if ccol > 0:
				a.append( (self.complete, ccol) )
			a.append((self.satt,len(cenc)))
			if maxcol-ccol-1 > 0:
				a.append( (self.normal, maxcol-ccol-1) )
			c._attr = [a]
			c._cs = [[(None, len(c._text[0]))]]
		else:
			c._attr = [[(self.complete,ccol),
				(self.normal,maxcol-ccol)]]
		return c

	def set_finished(self, done):
		"""
		done -- progress amount at 100%
		"""
		self.done = done
		self._invalidate()

	def get_text(self):
		percent = int( self.current*100/self.done )
		if percent < 0: percent = 0
		if percent > 100: percent = 100
		return Text( str(percent)+" %", 'center', 'clip' )

class CurrentSongProgress(ProgressBar_):
	def __init__(self, mpc, *args, **kwargs):
		super(CurrentSongProgress, self).__init__(*args, **kwargs)
		self.mpc = mpc
		signals.listen('idle_player', self._player_update)
		self._player_update()

	def get_text(self):
		if self._stopped is True:
			return urwid.Text('[Stopped]', 'right', 'clip')

		done = str(util.timedelta(seconds=self.done))
		current = str(util.timedelta(seconds=self.current))

		#TODO: config align, format
		text = "%s/%s"
		if self.mpc.status()['state'] == 'pause':
			text = '[Paused] ' + text
		text = urwid.Text(text % (current, done), 'right', 'clip')
		return text

	_progress_alarm = None
	_stopped = False
	def _player_update(self):
		"""Indicates that new song, pause, etc. more important than seconds++
		has happened."""
		status = self.mpc.status()
		if status['state'] == 'stop':
			self._stopped = True
			self.set_completion(0)
			self.set_finished(100) # Can't be 0, ZeroDivisionError in urwid.
			if self._progress_alarm is not None:
				signals.alarm_remove(self._progress_alarm)
				self._progress_alarm = None
			return True
		self._stopped = False

		# Something changed, better recalculate.
		assert 'time' in status # If we're not stopped, we must be on a track
		current, done = map(int, status['time'].split(':'))
		self.set_completion(current)
		self.set_finished(done)

		signals.redraw()

		if self._progress_alarm is not None:
			signals.alarm_remove(self._progress_alarm)
			self._progress_alarm = None
			
		if status['state'] == 'play':
			self._progress_alarm = signals.alarm_in(1.0, self._progress_increment)

	def _progress_increment(self, *_):
		#TODO?: Try to sync this to actual time more accurately?
		self._progress_alarm = signals.alarm_in(1.0, self._progress_increment)
		self.set_completion(self.current+1)
		signals.redraw()

class MainFooter(urwid.WidgetWrap):
	mpc = None
	_notification = None, None
	_notification_alarm = None

	# Valid widgets we can be rendering
	_components = '_progress_bar', '_notification_bar'
	_progress_bar, _notification_bar = None, None

	def __init__(self, mpc):
		self.mpc = mpc
		self._notification_bar = urwid.Text('')
		self._progress_bar = CurrentSongProgress(mpc,
		                                         ('footer', 'progress'),
		                                         ('footer', 'progress', 'elapsed'),
		                                         satt=('footer', 'progress', 'smoothed'))
		signals.listen('user_notification', self.notify)
		signals.listen('idle_update', self._notify_update)
		signals.listen('idle_playlist', self._playlist_update)

		super(MainFooter, self).__init__(self._progress_bar)
		self._change_current()

	def _change_current(self, name=None):
		if name in self._components:
			self._w = getattr(self, name)
		elif name is None:
			# Any logic to automatically determine current goes here.
			self._w = self._progress_bar

	def notify(self, message, interval=1.0): #TODO: Config interval default.
		"""Adds a notification to be displayed in the status bar.
		In addition to the mandatory message to be displayed, you may supply a
		desired duration in the interval parameter. This is a maximum duration,
		as any subsequent notification immediately overrides the current one."""
		#TODO?: Add 'level' param: ('info', 'warn', 'error', 'crit', etc.)
		#      and highlight accordingly, maybe let higher levels get priority.
		if self._notification_alarm:
			signals.alarm_remove(self._notification_alarm)
			self._notification_alarm = None
		self._change_current('_notification_bar')
		self._notification = None, None
		self._notification_bar.set_text(str(message))
		self._notification_alarm = signals.alarm_in(interval, self._clear_notification)
		signals.redraw()

	def _clear_notification(self, *_):
		self._notification = (None, None)
		self._notification_alarm = None
		self._change_current(None)
		signals.redraw()
		return False

	def _notify_update(self):
		if 'updating_db' not in self.mpc.status():
			signals.emit('user_notification', 'Database update finished!')
		# else: update ongoing, ignore

	def _playlist_update(self):
		if int(self.mpc.status()['playlistlength']) == 0:
			signals.emit('user_notification', 'Cleared playlist!')

class CurrentSong(urwid.Text):
	def __init__(self, mpc):
		self.mpc = mpc
		super(CurrentSong, self).__init__('')
		signals.listen('idle_player', self._player_update)
		self._player_update()

	def _player_update(self):
		if self.mpc.status()['state'] == 'stop':
			self.set_text('')
			return True

		item = self.mpc.currentsong()
		if 'artist' not in item: item['artist'] = '[None]'
		if 'title' not in item: item['title'] = '[None]'

		self.set_text('%s: %s' % (item['artist'], item['title']))
		return True

class DaemonFlags(urwid.Text):
	_flags = {}
	_flags_keys = 'Repeat', 'Random', 'Single', 'Consume', 'Crossfade', 'Update'
	_flags_mapping = {
		'Repeat': 'r',
		'Random': 'z',
		'Single': 's',
		'Consume': 'c',
		'Crossfade': 'x',
		'Update': 'U',
	}
	def __init__(self, mpc):
		self.mpc = mpc
		super(DaemonFlags, self).__init__('')
		signals.listen('idle_options', self._options_update)
		signals.listen('idle_update', self._options_update)
		self._flags = self._get_flags()
		self._render_flags()

	def _get_flags(self):
		flags = {}
		status = self.mpc.status()
		flags['Repeat'] = status['repeat'] == '1'
		flags['Random'] = status['random'] == '1'
		flags['Single'] = status['single'] == '1'
		flags['Consume'] = status['consume'] == '1'
		flags['Crossfade'] = int(status['xfade']) # not boolean
		flags['Update'] = 'updating_db' in status # not strictly boolean
		return flags

	def _options_update(self):
		newflags = self._get_flags()
		if newflags == self._flags:
			return False

		message = None
		onoff = lambda b: 'On' if b else 'Off'

		for mode in self._flags_keys:
			if mode == 'Update': continue
			if mode == 'Crossfade':
				if newflags['Crossfade'] != self._flags['Crossfade']:
					message = '%s set to %s seconds' % (mode, newflags[mode])
			elif newflags[mode] != self._flags[mode]:
				message = '%s mode is %s' % (mode, onoff(newflags[mode]))

		if message is not None:
			signals.emit('user_notification', message)

		self._flags = newflags
		return self._render_flags()

	def _render_flags(self):
		output = []
		for mode in self._flags_keys:
			if int(self._flags[mode]): # Avoids special-casing crossfade.
				output.append(self._flags_mapping[mode])
			else:
				output.append('-')

		output = '['+ ''.join(output) +']'
		self.set_text(output)
		return True

class MainHeader(urwid.Pile):
	def __init__(self, mpc):
		self.mpc = mpc
		self.currentsong = CurrentSong(mpc)

		self.flags = DaemonFlags(mpc)
		width = self.flags.pack()[0]
		self.flags = urwid.AttrMap(self.flags, ('header', 'flags'))

		self.topline = urwid.Columns((self.currentsong, ('fixed', width, self.flags)))

		border = urwid.Divider('─')
		self.border = urwid.AttrMap(border, ('header', 'border'))
		super(MainHeader, self).__init__((self.topline, self.border))

