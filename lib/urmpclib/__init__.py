if __name__ == '__main__':
	import os.path, sys
	sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

	import urwid
	import urmpd
	import signals
	from ui_main import MainFrame
	import configuration
	from configuration import config

	config.read('urmpclib/urmpc.conf.example')
	palette = configuration.extract_palette(config, 'palette')
	mpc = urmpd.MPDClient()
	mpc.connect(config.mpd.host, int(config.mpd.port))
	event_loop = urwid.SelectEventLoop()

	# Get urwid set up
	#FIXME: Passing None in here is ugly and will eventually break if urwid decides
	#       to be more strict about it.
	loop = urwid.MainLoop(None, palette, event_loop=event_loop)
	signals._mainloop = loop

	# Main widget uses mpd
	frame = MainFrame(mpc)
	loop.widget = frame

	# Idler runs cloned mpc connection
	idler = urmpd.Idler(mpc)
	event_loop.watch_file(idler, idler)

	try:
		loop.run()
	except KeyboardInterrupt as e:
		pass

