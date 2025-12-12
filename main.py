import gi
import os
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf


class WhiteboardArea(Gtk.DrawingArea):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK
        )
        self.strokes = []           # list of strokes, each stroke is a dict with 'points', 'color', 'size', 'is_eraser'
        self.current_stroke = None
        self.brush_size = 3

        # panning: shifting the "camera"
        self.offset_x = 0
        self.offset_y = 0
        self.is_panning = False
        self.pan_start_x = 0
        self.pan_start_y = 0

        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-release-event", self.on_button_release)

        self.set_hexpand(True)
        self.set_vexpand(True)

    def clear(self):
        self.strokes = []
        self.current_stroke = None
        self.queue_draw()

    def screen_to_world(self, sx, sy):
        """Convert screen coordinates to world coordinates (accounting for camera offset)."""
        return sx - self.offset_x, sy - self.offset_y

    def on_draw(self, widget, cr):
        # background
        cr.set_source_rgb(*self.app.bg_color)
        cr.paint()

        cr.set_line_cap(1)
        cr.set_line_join(1)

        # draw all the strokes
        for stroke in self.strokes:
            points = stroke['points']
            color = stroke['color']
            size = stroke['size']

            cr.set_source_rgb(*color)
            cr.set_line_width(size)

            if len(points) < 2:
                if points:
                    x, y = points[0]
                    cr.arc(x + self.offset_x, y + self.offset_y, size / 2, 0, 2 * 3.14159)
                    cr.fill()
                continue
            cr.move_to(points[0][0] + self.offset_x, points[0][1] + self.offset_y)
            for x, y in points[1:]:
                cr.line_to(x + self.offset_x, y + self.offset_y)
            cr.stroke()

        # The current stroke
        if self.current_stroke and len(self.current_stroke['points']) >= 2:
            cr.set_source_rgb(*self.current_stroke['color'])
            cr.set_line_width(self.current_stroke['size'])
            points = self.current_stroke['points']
            cr.move_to(points[0][0] + self.offset_x, points[0][1] + self.offset_y)
            for x, y in points[1:]:
                cr.line_to(x + self.offset_x, y + self.offset_y)
            cr.stroke()
        elif self.current_stroke and len(self.current_stroke['points']) == 1:
            cr.set_source_rgb(*self.current_stroke['color'])
            cr.set_line_width(self.current_stroke['size'])
            x, y = self.current_stroke['points'][0]
            cr.arc(x + self.offset_x, y + self.offset_y, self.current_stroke['size'] / 2, 0, 2 * 3.14159)
            cr.fill()

    def on_button_press(self, widget, event):
        if event.button == 3:
            self.is_panning = True
            self.pan_start_x = event.x
            self.pan_start_y = event.y
            self.get_window().set_cursor(Gdk.Cursor(Gdk.CursorType.FLEUR))
            return Gdk.EVENT_STOP

        elif event.button == 1 and not self.is_panning:
            wx, wy = self.screen_to_world(event.x, event.y)
            # Determine color based on eraser mode
            if self.app.eraser_mode:
                color = self.app.bg_color
            else:
                color = self.app.brush_color
            self.current_stroke = {
                'points': [(wx, wy)],
                'color': color,
                'size': self.brush_size,
                'is_eraser': self.app.eraser_mode
            }
            self.queue_draw()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_motion(self, widget, event):
        if self.is_panning:
            dx = event.x - self.pan_start_x
            dy = event.y - self.pan_start_y
            self.offset_x += dx
            self.offset_y += dy
            self.pan_start_x = event.x
            self.pan_start_y = event.y
            self.queue_draw()
            return Gdk.EVENT_STOP

        elif event.state & Gdk.ModifierType.BUTTON1_MASK and not self.is_panning:
            if self.current_stroke is not None:
                wx, wy = self.screen_to_world(event.x, event.y)
                self.current_stroke['points'].append((wx, wy))
                self.queue_draw()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_button_release(self, widget, event):
        if event.button == 3:
            self.is_panning = False
            self.get_window().set_cursor(Gdk.Cursor(Gdk.CursorType.LEFT_PTR))
            return Gdk.EVENT_STOP

        elif event.button == 1 and self.current_stroke is not None:
            if len(self.current_stroke['points']) > 0:
                self.strokes.append(self.current_stroke)
            self.current_stroke = None
            self.queue_draw()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE


class WhiteboardApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.example.whiteboard")
        self.connect("activate", self.on_activate)
        self.bg_color = (1.0, 1.0, 1.0)
        self.brush_color = (0.0, 0.0, 0.0)
        self.board = None
        self.dark_mode = False
        self.eraser_mode = False
        self.sidebar_visible = True

        # Get the directory where the script is located
        self.script_dir = os.path.dirname(os.path.abspath(__file__))

    def get_icon_path(self, icon_name):
        """Get the full path to an icon file."""
        return os.path.join(self.script_dir, "img", icon_name)

    def create_icon_button(self, icon_name, tooltip, callback=None):
        """Create a button with an icon from the img folder."""
        button = Gtk.Button()
        button.set_tooltip_text(tooltip)

        icon_path = self.get_icon_path(icon_name)
        if os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 24, 24)
                image = Gtk.Image.new_from_pixbuf(pixbuf)
                button.set_image(image)
                button.set_always_show_image(True)
            except Exception:
                button.set_label(tooltip[:3])
        else:
            button.set_label(tooltip[:3])

        if callback:
            button.connect("clicked", callback)

        # Style the button
        button.set_relief(Gtk.ReliefStyle.NONE)
        return button

    def on_activate(self, app):
        win = Gtk.ApplicationWindow(application=app, title="aboard")
        win.set_default_size(1000, 700)

        # Apply CSS for floating sidebar style
        css_provider = Gtk.CssProvider()
        css = b"""
        .floating-sidebar {
            background-color: rgba(50, 50, 50, 0.9);
            border-radius: 12px;
            padding: 8px;
        }
        .floating-sidebar button {
            background-color: rgba(70, 70, 70, 0.8);
            border-radius: 8px;
            border: none;
            min-width: 44px;
            min-height: 44px;
            margin: 4px;
            color: white;
        }
        .floating-sidebar button:hover {
            background-color: rgba(100, 100, 100, 0.9);
        }
        .floating-sidebar button:active,
        .floating-sidebar button.active {
            background-color: rgba(80, 140, 200, 0.9);
        }
        .floating-sidebar .size-label {
            color: white;
            font-size: 11px;
        }
        .menu-button {
            background-color: rgba(50, 50, 50, 0.8);
            border-radius: 8px;
            border: none;
            min-width: 40px;
            min-height: 40px;
        }
        .menu-button:hover {
            background-color: rgba(70, 70, 70, 0.9);
        }
        """
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        overlay = Gtk.Overlay()
        win.add(overlay)

        # Drawing area (full window)
        self.board = WhiteboardArea(self)
        overlay.add(self.board)

        # Floating sidebar container (positioned on left side)
        sidebar_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_container.set_halign(Gtk.Align.START)
        sidebar_container.set_valign(Gtk.Align.CENTER)
        sidebar_container.set_margin_start(15)

        # Floating sidebar
        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.sidebar.get_style_context().add_class("floating-sidebar")
        self.sidebar.set_margin_top(10)
        self.sidebar.set_margin_bottom(10)

        # Clear button (brush icon)
        clear_btn = self.create_icon_button("brush-symbolic.svg", "Clear", self.on_clear)
        self.sidebar.pack_start(clear_btn, False, False, 0)

        # Eraser button
        self.eraser_btn = self.create_icon_button("edit-clear-all-symbolic.svg", "Eraser", self.on_toggle_eraser)
        self.sidebar.pack_start(self.eraser_btn, False, False, 0)

        # Brush size button with popup
        size_btn = self.create_icon_button("app-icon-design-symbolic.svg", "Brush Size", None)
        size_popover = Gtk.Popover()
        size_popover.set_relative_to(size_btn)

        size_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        size_box.set_margin_top(10)
        size_box.set_margin_bottom(10)
        size_box.set_margin_start(10)
        size_box.set_margin_end(10)

        size_label = Gtk.Label(label="Brush Size: 3")
        size_box.pack_start(size_label, False, False, 0)

        size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 50, 1)
        size_scale.set_value(3)
        size_scale.set_size_request(150, -1)
        size_scale.connect("value-changed", self.on_brush_size_changed, size_label)
        size_box.pack_start(size_scale, False, False, 0)

        size_popover.add(size_box)
        size_popover.show_all()
        size_btn.connect("clicked", lambda b: size_popover.popup())
        self.sidebar.pack_start(size_btn, False, False, 0)

        # Dark mode toggle button
        self.dark_mode_btn = self.create_icon_button("dark-mode-symbolic.svg", "Dark Mode", self.on_toggle_dark_mode)
        self.sidebar.pack_start(self.dark_mode_btn, False, False, 0)

        sidebar_container.pack_start(self.sidebar, False, False, 0)
        overlay.add_overlay(sidebar_container)

        # Burger menu button (top right)
        menu_btn = Gtk.MenuButton()
        menu_btn.set_halign(Gtk.Align.END)
        menu_btn.set_valign(Gtk.Align.START)
        menu_btn.set_margin_end(15)
        menu_btn.set_margin_top(15)
        menu_btn.get_style_context().add_class("menu-button")

        # Set menu icon
        menu_icon_path = self.get_icon_path("menu-symbolic.svg")
        if os.path.exists(menu_icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(menu_icon_path, 20, 20)
                menu_image = Gtk.Image.new_from_pixbuf(pixbuf)
                menu_btn.set_image(menu_image)
            except Exception:
                pass

        # Menu popup
        menu = Gtk.Menu()

        toggle_sidebar_item = Gtk.MenuItem(label="Toggle Sidebar")
        toggle_sidebar_item.connect("activate", self.on_toggle_sidebar)
        menu.append(toggle_sidebar_item)

        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self.on_about)
        menu.append(about_item)

        menu.show_all()
        menu_btn.set_popup(menu)

        overlay.add_overlay(menu_btn)

        win.show_all()

    def on_clear(self, button):
        if self.board:
            self.board.clear()

    def on_toggle_eraser(self, button):
        self.eraser_mode = not self.eraser_mode
        if self.eraser_mode:
            button.get_style_context().add_class("active")
        else:
            button.get_style_context().remove_class("active")

    def on_brush_size_changed(self, scale, label):
        size = int(scale.get_value())
        self.board.brush_size = size
        label.set_text(f"Brush Size: {size}")

    def on_toggle_dark_mode(self, button):
        self.dark_mode = not self.dark_mode
        if self.dark_mode:
            self.bg_color = (0.0, 0.0, 0.0)
            self.brush_color = (1.0, 1.0, 1.0)
            button.get_style_context().add_class("active")
        else:
            self.bg_color = (1.0, 1.0, 1.0)
            self.brush_color = (0.0, 0.0, 0.0)
            button.get_style_context().remove_class("active")

        # Update eraser strokes color to match new background
        if self.board:
            for stroke in self.board.strokes:
                if stroke.get('is_eraser', False):
                    stroke['color'] = self.bg_color
            self.board.queue_draw()

    def on_toggle_sidebar(self, item):
        self.sidebar_visible = not self.sidebar_visible
        if self.sidebar_visible:
            self.sidebar.show()
        else:
            self.sidebar.hide()

    def on_about(self, item):
        dialog = Gtk.MessageDialog(
            transient_for=self.get_active_window(),
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Aboard Whiteboard"
        )
        dialog.format_secondary_text(
            "A simple interactive whiteboard application.\n\n"
            "Controls:\n"
            "• Left click: Draw\n"
            "• Right click + drag: Pan\n"
            "• Use toolbar for tools"
        )
        dialog.run()
        dialog.destroy()


if __name__ == "__main__":
    app = WhiteboardApp()
    app.run()
