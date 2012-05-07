# -*- coding: utf-8 -*-
import urwid

import signals
import util
from configuration import config

#TODO: Remove this on next urwid release, this has been added.
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
		self._progress_alarm = signals.alarm_in(1.0, self._progress_increment)
		self.set_completion(self.current+1)
		signals.redraw()

class MainFooter(util.WidgetMux):
	def __init__(self, mpc, parent):
		self.mpc = mpc
		self.parent = parent
		self._notification = None, None
		self._notification_alarm = None
		self.main_panel = 'progress_bar'
		notifications = urwid.Text('')
		progress = CurrentSongProgress(mpc,
			 'footer.progress',
			 'footer.progress.elapsed',
			 satt='footer.progress.smoothed')

		widgets = {'progress_bar': progress, 'notification_bar': notifications}
		super(MainFooter, self).__init__(widgets, self.main_panel)

		signals.listen('user_notification', self.notify)
		signals.listen('user_interactive', self.interaction)
		signals.listen('user_interactive_end', self.interaction_end)
		signals.listen('idle_update', self._notify_update)
		signals.listen('idle_playlist', self._playlist_update)

	def notify(self, message, interval=1.0): #TODO: Config interval default.
		"""Adds a notification to be displayed in the status bar.
		In addition to the mandatory message to be displayed, you may supply a
		desired duration in the interval parameter. This is a maximum duration,
		as any subsequent notification immediately overrides the current one."""
		if self._notification_alarm:
			signals.alarm_remove(self._notification_alarm)
			self._notification_alarm = None
		self._notification = None, None
		self._notification_alarm = signals.alarm_in(interval, self._clear_notification)
		self.widget_dict['notification_bar'].set_text(str(message))
		self.switch('notification_bar')

	def interaction(self, widget):
		"""Temporarily display another widget for user input."""
		self.widget_dict['interactive'] = widget
		self.main_panel = 'interactive'
		self.switch('interactive')
		self.parent.set_focus('footer')

	def interaction_end(self):
		self.main_panel = 'progress_bar'
		self.switch(self.main_panel)
		self.parent.set_focus('body')

	def _clear_notification(self, *_):
		self._notification = (None, None)
		self._notification_alarm = None
		self.switch(self.main_panel)
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
		super(CurrentSong, self).__init__('', wrap='clip')
		signals.listen('idle_player', self._player_update)
		self._player_update()

	def _player_update(self):
		if self.mpc.status()['state'] == 'stop':
			self.set_text('')
			return True

		item = self.mpc.currentsong()
		if 'artist' not in item: item['artist'] = config.format.empty_tag
		if 'title' not in item: item['title'] = config.format.empty_tag

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
		self.flags = urwid.AttrMap(self.flags, 'header.flags', 'header.flags')

		self.topline = urwid.Columns((self.currentsong, ('fixed', width, self.flags)))

		border = urwid.Divider(config.format.header.divider)
		self.border = urwid.AttrMap(border, 'header.border', 'header.border')
		super(MainHeader, self).__init__((self.topline, self.border))

