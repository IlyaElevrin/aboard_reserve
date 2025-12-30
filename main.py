import gi
import os
import math
import json
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Pango, GLib


def catmull_rom_spline(points, num_segments=10):
    """
    Apply Catmull-Rom spline interpolation for smooth curves.
    Returns a list of smoothed points.
    """
    if len(points) < 4:
        return points

    smoothed = []

    # Add first point
    smoothed.append(points[0])

    for i in range(len(points) - 3):
        p0 = points[i]
        p1 = points[i + 1]
        p2 = points[i + 2]
        p3 = points[i + 3]

        for t in range(1, num_segments + 1):
            t_norm = t / num_segments
            t2 = t_norm * t_norm
            t3 = t2 * t_norm

            # Catmull-Rom spline formula
            x = 0.5 * ((2 * p1[0]) +
                      (-p0[0] + p2[0]) * t_norm +
                      (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 +
                      (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)

            y = 0.5 * ((2 * p1[1]) +
                      (-p0[1] + p2[1]) * t_norm +
                      (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 +
                      (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)

            smoothed.append((x, y))

    # Add last two points
    smoothed.append(points[-2])
    smoothed.append(points[-1])

    return smoothed


class WhiteboardArea(Gtk.DrawingArea):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.set_events(
            Gdk.EventMask.BUTTON_PRESS_MASK |
            Gdk.EventMask.POINTER_MOTION_MASK |
            Gdk.EventMask.BUTTON_RELEASE_MASK |
            Gdk.EventMask.SCROLL_MASK |
            Gdk.EventMask.KEY_PRESS_MASK
        )
        self.strokes = []           # list of strokes, each stroke is a dict with 'points', 'color', 'size', 'is_eraser'
        self.current_stroke = None
        self.brush_size = 3
        self.shapes = []            # list of shapes: {'type': 'rect'/'circle'/'triangle'/'arrow', 'x', 'y', 'w', 'h', 'color', 'size'}
        self.current_shape = None
        self.shape_start_x = 0
        self.shape_start_y = 0
        self.text_items = []        # list of text items: {'text', 'x', 'y', 'color', 'font_size'}
        self.images = []            # list of images: {'pixbuf', 'x', 'y', 'width', 'height'}

        # panning: shifting the "camera"
        self.offset_x = 0
        self.offset_y = 0
        self.is_panning = False
        self.pan_start_x = 0
        self.pan_start_y = 0

        # zoom
        self.zoom = 1.0
        self.min_zoom = 0.1
        self.max_zoom = 5.0

        self.connect("draw", self.on_draw)
        self.connect("button-press-event", self.on_button_press)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("button-release-event", self.on_button_release)
        self.connect("scroll-event", self.on_scroll)

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_can_focus(True)

    def clear(self):
        self.strokes = []
        self.current_stroke = None
        self.shapes = []
        self.current_shape = None
        self.text_items = []
        self.images = []
        self.queue_draw()

    def screen_to_world(self, sx, sy):
        """Convert screen coordinates to world coordinates (accounting for camera offset and zoom)."""
        return (sx - self.offset_x) / self.zoom, (sy - self.offset_y) / self.zoom

    def world_to_screen(self, wx, wy):
        """Convert world coordinates to screen coordinates."""
        return wx * self.zoom + self.offset_x, wy * self.zoom + self.offset_y

    def on_scroll(self, widget, event):
        """Handle mouse wheel scrolling for zoom."""
        # Get mouse position for zoom center
        mouse_x, mouse_y = event.x, event.y

        # Get world position before zoom
        world_x, world_y = self.screen_to_world(mouse_x, mouse_y)

        # Calculate zoom factor
        if event.direction == Gdk.ScrollDirection.UP:
            zoom_factor = 1.1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            zoom_factor = 0.9
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            # Handle smooth scrolling
            _, dx, dy = event.get_scroll_deltas()
            if dy < 0:
                zoom_factor = 1.1
            elif dy > 0:
                zoom_factor = 0.9
            else:
                return Gdk.EVENT_PROPAGATE
        else:
            return Gdk.EVENT_PROPAGATE

        # Apply zoom
        new_zoom = self.zoom * zoom_factor
        new_zoom = max(self.min_zoom, min(self.max_zoom, new_zoom))

        if new_zoom != self.zoom:
            self.zoom = new_zoom

            # Adjust offset to keep mouse position at the same world location
            new_screen_x, new_screen_y = self.world_to_screen(world_x, world_y)
            self.offset_x += mouse_x - new_screen_x
            self.offset_y += mouse_y - new_screen_y

            self.queue_draw()

        return Gdk.EVENT_STOP

    def on_draw(self, widget, cr):
        # background
        cr.set_source_rgb(*self.app.bg_color)
        cr.paint()

        cr.set_line_cap(1)  # CAIRO_LINE_CAP_ROUND
        cr.set_line_join(1)  # CAIRO_LINE_JOIN_ROUND

        # Draw images
        for img in self.images:
            sx, sy = self.world_to_screen(img['x'], img['y'])
            scaled_width = img['width'] * self.zoom
            scaled_height = img['height'] * self.zoom

            # Scale pixbuf
            scaled_pixbuf = img['pixbuf'].scale_simple(
                int(scaled_width), int(scaled_height),
                GdkPixbuf.InterpType.BILINEAR
            )

            Gdk.cairo_set_source_pixbuf(cr, scaled_pixbuf, sx, sy)
            cr.paint()

        # draw all the strokes
        for stroke in self.strokes:
            points = stroke['points']
            color = stroke['color']
            size = stroke['size']

            cr.set_source_rgb(*color)
            cr.set_line_width(size * self.zoom)

            if len(points) < 2:
                if points:
                    sx, sy = self.world_to_screen(points[0][0], points[0][1])
                    cr.arc(sx, sy, size * self.zoom / 2, 0, 2 * math.pi)
                    cr.fill()
                continue

            # Apply smoothing for longer strokes
            if len(points) >= 4:
                smoothed_points = catmull_rom_spline(points, num_segments=5)
            else:
                smoothed_points = points

            sx, sy = self.world_to_screen(smoothed_points[0][0], smoothed_points[0][1])
            cr.move_to(sx, sy)
            for x, y in smoothed_points[1:]:
                sx, sy = self.world_to_screen(x, y)
                cr.line_to(sx, sy)
            cr.stroke()

        # Draw shapes
        for shape in self.shapes:
            self.draw_shape(cr, shape)

        # Draw current shape being created
        if self.current_shape:
            self.draw_shape(cr, self.current_shape)

        # Draw text items
        for text_item in self.text_items:
            self.draw_text_item(cr, text_item)

        # The current stroke
        if self.current_stroke and len(self.current_stroke['points']) >= 2:
            cr.set_source_rgb(*self.current_stroke['color'])
            cr.set_line_width(self.current_stroke['size'] * self.zoom)
            points = self.current_stroke['points']

            # Apply smoothing
            if len(points) >= 4:
                smoothed_points = catmull_rom_spline(points, num_segments=5)
            else:
                smoothed_points = points

            sx, sy = self.world_to_screen(smoothed_points[0][0], smoothed_points[0][1])
            cr.move_to(sx, sy)
            for x, y in smoothed_points[1:]:
                sx, sy = self.world_to_screen(x, y)
                cr.line_to(sx, sy)
            cr.stroke()
        elif self.current_stroke and len(self.current_stroke['points']) == 1:
            cr.set_source_rgb(*self.current_stroke['color'])
            cr.set_line_width(self.current_stroke['size'] * self.zoom)
            x, y = self.current_stroke['points'][0]
            sx, sy = self.world_to_screen(x, y)
            cr.arc(sx, sy, self.current_stroke['size'] * self.zoom / 2, 0, 2 * math.pi)
            cr.fill()

    def draw_shape(self, cr, shape):
        """Draw a shape on the canvas."""
        cr.set_source_rgb(*shape['color'])
        cr.set_line_width(shape['size'] * self.zoom)

        sx, sy = self.world_to_screen(shape['x'], shape['y'])
        sw = shape['w'] * self.zoom
        sh = shape['h'] * self.zoom

        shape_type = shape['type']

        if shape_type == 'rect':
            # Rounded rectangle
            radius = min(abs(sw), abs(sh)) * 0.1
            radius = min(radius, 20)

            # Handle negative dimensions
            x = sx if sw >= 0 else sx + sw
            y = sy if sh >= 0 else sy + sh
            w = abs(sw)
            h = abs(sh)

            if w > 0 and h > 0:
                # Draw rounded rectangle
                cr.new_sub_path()
                cr.arc(x + w - radius, y + radius, radius, -math.pi/2, 0)
                cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi/2)
                cr.arc(x + radius, y + h - radius, radius, math.pi/2, math.pi)
                cr.arc(x + radius, y + radius, radius, math.pi, 3*math.pi/2)
                cr.close_path()
                cr.stroke()

        elif shape_type == 'circle':
            # Calculate center and radius
            cx = sx + sw / 2
            cy = sy + sh / 2
            radius = min(abs(sw), abs(sh)) / 2

            cr.arc(cx, cy, radius, 0, 2 * math.pi)
            cr.stroke()

        elif shape_type == 'triangle':
            # Handle negative dimensions
            x = sx if sw >= 0 else sx + sw
            y = sy if sh >= 0 else sy + sh
            w = abs(sw)
            h = abs(sh)

            # Equilateral-ish triangle pointing up
            cr.move_to(x + w / 2, y)
            cr.line_to(x + w, y + h)
            cr.line_to(x, y + h)
            cr.close_path()
            cr.stroke()

        elif shape_type == 'arrow':
            # Draw arrow from start to end point
            x1, y1 = sx, sy
            x2, y2 = sx + sw, sy + sh

            # Arrow body
            cr.move_to(x1, y1)
            cr.line_to(x2, y2)
            cr.stroke()

            # Arrow head
            arrow_length = 15 * self.zoom
            arrow_angle = math.pi / 6  # 30 degrees

            angle = math.atan2(y2 - y1, x2 - x1)

            # Left part of arrow head
            cr.move_to(x2, y2)
            cr.line_to(
                x2 - arrow_length * math.cos(angle - arrow_angle),
                y2 - arrow_length * math.sin(angle - arrow_angle)
            )
            cr.stroke()

            # Right part of arrow head
            cr.move_to(x2, y2)
            cr.line_to(
                x2 - arrow_length * math.cos(angle + arrow_angle),
                y2 - arrow_length * math.sin(angle + arrow_angle)
            )
            cr.stroke()

    def draw_text_item(self, cr, text_item):
        """Draw a text item on the canvas."""
        sx, sy = self.world_to_screen(text_item['x'], text_item['y'])

        cr.set_source_rgb(*text_item['color'])
        cr.select_font_face("Sans", 0, 0)  # CAIRO_FONT_SLANT_NORMAL, CAIRO_FONT_WEIGHT_NORMAL
        cr.set_font_size(text_item['font_size'] * self.zoom)

        cr.move_to(sx, sy)
        cr.show_text(text_item['text'])

    def on_button_press(self, widget, event):
        if event.button == 3:
            self.is_panning = True
            self.pan_start_x = event.x
            self.pan_start_y = event.y
            self.get_window().set_cursor(Gdk.Cursor(Gdk.CursorType.FLEUR))
            return Gdk.EVENT_STOP

        elif event.button == 1 and not self.is_panning:
            wx, wy = self.screen_to_world(event.x, event.y)

            # Check if text tool is active
            if self.app.current_tool == 'text':
                self.app.show_text_input_dialog(wx, wy)
                return Gdk.EVENT_STOP

            # Check if shape tool is active
            if self.app.current_tool == 'shape':
                self.shape_start_x = wx
                self.shape_start_y = wy
                self.current_shape = {
                    'type': self.app.current_shape_type,
                    'x': wx,
                    'y': wy,
                    'w': 0,
                    'h': 0,
                    'color': self.app.brush_color,
                    'size': self.brush_size
                }
                return Gdk.EVENT_STOP

            # Default: brush tool
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
            wx, wy = self.screen_to_world(event.x, event.y)

            # Shape drawing
            if self.current_shape is not None:
                self.current_shape['w'] = wx - self.shape_start_x
                self.current_shape['h'] = wy - self.shape_start_y
                self.queue_draw()
                return Gdk.EVENT_STOP

            # Brush drawing
            if self.current_stroke is not None:
                self.current_stroke['points'].append((wx, wy))
                self.queue_draw()
            return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def on_button_release(self, widget, event):
        if event.button == 3:
            self.is_panning = False
            self.get_window().set_cursor(Gdk.Cursor(Gdk.CursorType.LEFT_PTR))
            return Gdk.EVENT_STOP

        elif event.button == 1:
            # Shape creation
            if self.current_shape is not None:
                if abs(self.current_shape['w']) > 5 or abs(self.current_shape['h']) > 5:
                    self.shapes.append(self.current_shape)
                self.current_shape = None
                self.queue_draw()
                return Gdk.EVENT_STOP

            # Stroke creation
            if self.current_stroke is not None:
                if len(self.current_stroke['points']) > 0:
                    self.strokes.append(self.current_stroke)
                self.current_stroke = None
                self.queue_draw()
                return Gdk.EVENT_STOP

        return Gdk.EVENT_PROPAGATE

    def add_text(self, text, x, y):
        """Add text at the specified world coordinates."""
        if text.strip():
            self.text_items.append({
                'text': text,
                'x': x,
                'y': y,
                'color': self.app.brush_color,
                'font_size': max(12, self.brush_size * 4)
            })
            self.queue_draw()

    def add_image(self, pixbuf, x, y):
        """Add an image at the specified world coordinates."""
        # Scale large images down
        max_size = 500
        width = pixbuf.get_width()
        height = pixbuf.get_height()

        if width > max_size or height > max_size:
            scale = min(max_size / width, max_size / height)
            width = int(width * scale)
            height = int(height * scale)
            pixbuf = pixbuf.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)

        self.images.append({
            'pixbuf': pixbuf,
            'x': x,
            'y': y,
            'width': width,
            'height': height
        })
        self.queue_draw()

    def get_board_data(self):
        """Serialize board data for saving."""
        data = {
            'strokes': [],
            'shapes': self.shapes.copy(),
            'text_items': self.text_items.copy(),
            'offset_x': self.offset_x,
            'offset_y': self.offset_y,
            'zoom': self.zoom,
            'brush_size': self.brush_size
        }
        # Serialize strokes (excluding pixbuf data from images)
        for stroke in self.strokes:
            data['strokes'].append({
                'points': stroke['points'],
                'color': stroke['color'],
                'size': stroke['size'],
                'is_eraser': stroke.get('is_eraser', False)
            })
        return data

    def load_board_data(self, data):
        """Load board data from saved state."""
        self.strokes = data.get('strokes', [])
        self.shapes = data.get('shapes', [])
        self.text_items = data.get('text_items', [])
        self.offset_x = data.get('offset_x', 0)
        self.offset_y = data.get('offset_y', 0)
        self.zoom = data.get('zoom', 1.0)
        self.brush_size = data.get('brush_size', 3)
        self.images = []  # Images are not saved/loaded
        self.queue_draw()


class MainMenuWindow(Gtk.Window):
    """Main menu window for board management."""
    def __init__(self, app):
        super().__init__(title="Aboard - Whiteboard")
        self.app = app
        self.set_default_size(800, 600)
        self.set_position(Gtk.WindowPosition.CENTER)

        # Get the directory where the script is located
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.save_dir = os.path.join(self.script_dir, "board_save")

        # Ensure save directory exists
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

        # Apply CSS styling
        self.apply_css()

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        main_box.set_margin_top(40)
        main_box.set_margin_bottom(40)
        main_box.set_margin_start(40)
        main_box.set_margin_end(40)
        self.add(main_box)

        # Header with logo and title
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        header_box.set_halign(Gtk.Align.CENTER)

        # Load logo
        logo_path = os.path.join(self.script_dir, "logo.svg")
        if os.path.exists(logo_path):
            try:
                logo_pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(logo_path, 64, 64)
                logo_image = Gtk.Image.new_from_pixbuf(logo_pixbuf)
                header_box.pack_start(logo_image, False, False, 0)
            except Exception:
                pass

        title_label = Gtk.Label()
        title_label.set_markup("<span size='xx-large' weight='bold'>Aboard Whiteboard</span>")
        header_box.pack_start(title_label, False, False, 0)

        main_box.pack_start(header_box, False, False, 0)

        # Scrolled window for board tiles
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        # Flow box for tile layout
        self.flowbox = Gtk.FlowBox()
        self.flowbox.set_valign(Gtk.Align.START)
        self.flowbox.set_max_children_per_line(4)
        self.flowbox.set_min_children_per_line(2)
        self.flowbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flowbox.set_homogeneous(True)
        self.flowbox.set_column_spacing(20)
        self.flowbox.set_row_spacing(20)

        scrolled.add(self.flowbox)
        main_box.pack_start(scrolled, True, True, 0)

        # Load boards
        self.refresh_boards()

        self.connect("destroy", self.on_destroy)
        self.show_all()

    def apply_css(self):
        """Apply CSS styling for the main menu."""
        css_provider = Gtk.CssProvider()
        css = b"""
        window {
            background-color: #f5f5f5;
        }
        .board-tile {
            background-color: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            min-width: 150px;
            min-height: 150px;
        }
        .board-tile:hover {
            background-color: #fafafa;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        }
        .new-board-tile {
            background-color: #e8f5e9;
            border: 2px dashed #4caf50;
        }
        .new-board-tile:hover {
            background-color: #c8e6c9;
        }
        .board-tile-label {
            font-size: 14px;
            font-weight: bold;
            color: #333;
        }
        .delete-button {
            background-color: #ffebee;
            border-radius: 50%;
            min-width: 24px;
            min-height: 24px;
            padding: 0;
        }
        .delete-button:hover {
            background-color: #ffcdd2;
        }
        """
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def refresh_boards(self):
        """Refresh the list of saved boards."""
        # Clear existing tiles
        for child in self.flowbox.get_children():
            self.flowbox.remove(child)

        # Add "New Board" tile first
        new_tile = self.create_new_board_tile()
        self.flowbox.add(new_tile)

        # Load saved boards
        if os.path.exists(self.save_dir):
            for filename in sorted(os.listdir(self.save_dir)):
                if filename.endswith('.json'):
                    board_name = filename[:-5]  # Remove .json extension
                    tile = self.create_board_tile(board_name)
                    self.flowbox.add(tile)

        self.flowbox.show_all()

    def create_new_board_tile(self):
        """Create the 'New Board' tile."""
        tile = Gtk.Button()
        tile.get_style_context().add_class("board-tile")
        tile.get_style_context().add_class("new-board-tile")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_halign(Gtk.Align.CENTER)
        content.set_valign(Gtk.Align.CENTER)

        # Plus icon
        plus_label = Gtk.Label()
        plus_label.set_markup("<span size='xx-large'>+</span>")
        content.pack_start(plus_label, False, False, 0)

        # Text
        text_label = Gtk.Label(label="New Board")
        text_label.get_style_context().add_class("board-tile-label")
        content.pack_start(text_label, False, False, 0)

        tile.add(content)
        tile.connect("clicked", self.on_new_board_clicked)

        return tile

    def create_board_tile(self, board_name):
        """Create a tile for an existing board."""
        tile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        tile_box.get_style_context().add_class("board-tile")

        # Board button
        board_btn = Gtk.Button()
        board_btn.set_relief(Gtk.ReliefStyle.NONE)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        content.set_halign(Gtk.Align.CENTER)
        content.set_valign(Gtk.Align.CENTER)

        # Board icon
        icon_label = Gtk.Label()
        icon_label.set_markup("<span size='xx-large'>📋</span>")
        content.pack_start(icon_label, False, False, 0)

        # Board name
        name_label = Gtk.Label(label=board_name)
        name_label.get_style_context().add_class("board-tile-label")
        name_label.set_ellipsize(Pango.EllipsizeMode.END)
        name_label.set_max_width_chars(15)
        content.pack_start(name_label, False, False, 0)

        board_btn.add(content)
        board_btn.connect("clicked", self.on_board_clicked, board_name)

        tile_box.pack_start(board_btn, True, True, 0)

        # Delete button
        delete_btn = Gtk.Button(label="✕")
        delete_btn.get_style_context().add_class("delete-button")
        delete_btn.set_halign(Gtk.Align.END)
        delete_btn.connect("clicked", self.on_delete_board, board_name)
        tile_box.pack_start(delete_btn, False, False, 0)

        return tile_box

    def on_new_board_clicked(self, button):
        """Show theme selection dialog and create new board."""
        dialog = Gtk.Dialog(
            title="Create New Board",
            transient_for=self,
            flags=0
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK
        )

        content = dialog.get_content_area()
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)
        content.set_spacing(15)

        # Board name entry
        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        name_label = Gtk.Label(label="Board Name:")
        name_entry = Gtk.Entry()
        name_entry.set_text("Untitled Board")
        name_entry.set_width_chars(25)
        name_box.pack_start(name_label, False, False, 0)
        name_box.pack_start(name_entry, True, True, 0)
        content.pack_start(name_box, False, False, 0)

        # Theme selection
        theme_label = Gtk.Label(label="Select Theme:")
        theme_label.set_halign(Gtk.Align.START)
        content.pack_start(theme_label, False, False, 0)

        theme_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        theme_box.set_halign(Gtk.Align.CENTER)

        # Light theme (default - black on white)
        light_btn = Gtk.RadioButton.new_with_label(None, "Light (Default)")
        light_preview = Gtk.DrawingArea()
        light_preview.set_size_request(60, 40)
        light_preview.connect("draw", lambda w, cr: self.draw_theme_preview(cr, True))

        light_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        light_box.pack_start(light_preview, False, False, 0)
        light_box.pack_start(light_btn, False, False, 0)
        theme_box.pack_start(light_box, False, False, 0)

        # Dark theme (white on black)
        dark_btn = Gtk.RadioButton.new_with_label_from_widget(light_btn, "Dark")
        dark_preview = Gtk.DrawingArea()
        dark_preview.set_size_request(60, 40)
        dark_preview.connect("draw", lambda w, cr: self.draw_theme_preview(cr, False))

        dark_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        dark_box.pack_start(dark_preview, False, False, 0)
        dark_box.pack_start(dark_btn, False, False, 0)
        theme_box.pack_start(dark_box, False, False, 0)

        content.pack_start(theme_box, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            board_name = name_entry.get_text().strip() or "Untitled Board"
            dark_mode = dark_btn.get_active()
            dialog.destroy()
            self.open_board(board_name, dark_mode=dark_mode, is_new=True)
        else:
            dialog.destroy()

    def draw_theme_preview(self, cr, is_light):
        """Draw a theme preview."""
        if is_light:
            cr.set_source_rgb(1, 1, 1)
        else:
            cr.set_source_rgb(0, 0, 0)
        cr.paint()

        # Draw sample stroke
        if is_light:
            cr.set_source_rgb(0, 0, 0)
        else:
            cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(2)
        cr.move_to(10, 20)
        cr.curve_to(20, 10, 40, 30, 50, 20)
        cr.stroke()

    def on_board_clicked(self, button, board_name):
        """Open an existing board."""
        self.open_board(board_name, is_new=False)

    def on_delete_board(self, button, board_name):
        """Delete a saved board."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Delete board '{board_name}'?"
        )
        dialog.format_secondary_text("This action cannot be undone.")

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            filepath = os.path.join(self.save_dir, f"{board_name}.json")
            if os.path.exists(filepath):
                os.remove(filepath)
            self.refresh_boards()

    def open_board(self, board_name, dark_mode=False, is_new=True):
        """Open the whiteboard editor."""
        self.hide()
        self.app.open_whiteboard(self, board_name, dark_mode=dark_mode, is_new=is_new)

    def on_destroy(self, widget):
        """Handle window close."""
        Gtk.main_quit()


class WhiteboardWindow(Gtk.Window):
    """Whiteboard editor window."""
    def __init__(self, app, main_menu, board_name, dark_mode=False, is_new=True):
        super().__init__(title=f"Aboard - {board_name}")
        self.app = app
        self.main_menu = main_menu
        self.board_name = board_name
        self.set_default_size(1000, 700)

        # Set theme based on selection
        if dark_mode:
            self.app.bg_color = (0.0, 0.0, 0.0)
            self.app.brush_color = (1.0, 1.0, 1.0)
            self.app.dark_mode = True
        else:
            self.app.bg_color = (1.0, 1.0, 1.0)
            self.app.brush_color = (0.0, 0.0, 0.0)
            self.app.dark_mode = False

        # Get the directory where the script is located
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.save_dir = os.path.join(self.script_dir, "board_save")

        # Apply CSS for floating sidebar style
        self.apply_css()

        overlay = Gtk.Overlay()
        self.add(overlay)

        # Drawing area (full window)
        self.app.board = WhiteboardArea(self.app)
        overlay.add(self.app.board)

        # Load existing board data if not new
        if not is_new:
            self.load_board()

        # Enable drag and drop for images
        self.app.board.drag_dest_set(
            Gtk.DestDefaults.ALL,
            [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
            Gdk.DragAction.COPY
        )
        self.app.board.connect("drag-data-received", self.on_drag_data_received)

        # Create sidebar
        self.create_sidebar(overlay)

        # Create burger menu
        self.create_burger_menu(overlay)

        # Connect key press for paste (Ctrl+V)
        self.connect("key-press-event", self.on_key_press)
        self.connect("delete-event", self.on_close)

        self.show_all()

    def apply_css(self):
        """Apply CSS styling."""
        css_provider = Gtk.CssProvider()
        css = b"""
        .floating-sidebar {
            background-color: rgba(30, 30, 30, 0.85);
            border-radius: 12px;
            padding: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        .floating-sidebar button {
            background-color: rgba(50, 50, 50, 0.9);
            border-radius: 8px;
            border: none;
            min-width: 44px;
            min-height: 44px;
            margin: 4px;
            color: white;
        }
        .floating-sidebar button:hover {
            background-color: rgba(80, 80, 80, 0.95);
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
            background-color: rgba(30, 30, 30, 0.85);
            border-radius: 8px;
            border: none;
            min-width: 40px;
            min-height: 40px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
        }
        .menu-button:hover {
            background-color: rgba(50, 50, 50, 0.9);
        }
        .color-button {
            border-radius: 50%;
            min-width: 32px;
            min-height: 32px;
            padding: 0;
            border: 2px solid rgba(255, 255, 255, 0.3);
        }
        .color-button:hover {
            border: 2px solid rgba(255, 255, 255, 0.6);
        }
        .shape-menu {
            background-color: rgba(40, 40, 40, 0.95);
            border-radius: 8px;
            padding: 8px;
        }
        .shape-menu button {
            background-color: rgba(60, 60, 60, 0.9);
            border-radius: 6px;
            border: none;
            min-width: 36px;
            min-height: 36px;
            margin: 2px;
        }
        .shape-menu button:hover {
            background-color: rgba(90, 90, 90, 0.95);
        }
        .shape-menu button.active {
            background-color: rgba(80, 140, 200, 0.9);
        }
        .size-popover {
            background-color: rgba(40, 40, 40, 0.95);
            border-radius: 8px;
        }
        .size-popover label {
            color: white;
        }
        """
        css_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def create_sidebar(self, overlay):
        """Create the floating sidebar."""
        sidebar_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_container.set_halign(Gtk.Align.START)
        sidebar_container.set_valign(Gtk.Align.CENTER)
        sidebar_container.set_margin_start(15)

        self.sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.sidebar.get_style_context().add_class("floating-sidebar")
        self.sidebar.set_margin_top(10)
        self.sidebar.set_margin_bottom(10)

        # Brush/Draw button with right-click for size
        self.brush_btn = self.create_icon_button("brush-symbolic.svg", "Brush (Right-click for size)")
        self.brush_btn.get_style_context().add_class("active")
        self.brush_btn.connect("clicked", self.on_select_brush)
        self.brush_btn.connect("button-press-event", self.on_brush_button_press)
        self.sidebar.pack_start(self.brush_btn, False, False, 0)

        # Eraser button with right-click for size
        self.eraser_btn = self.create_icon_button("edit-clear-all-symbolic.svg", "Eraser (Right-click for size)")
        self.eraser_btn.connect("clicked", self.on_toggle_eraser)
        self.eraser_btn.connect("button-press-event", self.on_eraser_button_press)
        self.sidebar.pack_start(self.eraser_btn, False, False, 0)

        # Create brush size popover (shared between brush and eraser)
        self.create_size_popover()

        # Shapes button with popup menu
        self.shapes_btn = self.create_icon_button("shapes-large-symbolic.svg", "Shapes")
        self.create_shapes_popover()
        self.shapes_btn.connect("clicked", lambda b: (self.on_select_shape(b), self.shapes_popover.popup()))
        self.sidebar.pack_start(self.shapes_btn, False, False, 0)

        # Text tool button
        self.text_btn = self.create_icon_button("draw-text-symbolic.svg", "Text")
        self.text_btn.connect("clicked", self.on_select_text)
        self.sidebar.pack_start(self.text_btn, False, False, 0)

        # Color picker button
        self.color_btn = Gtk.ColorButton()
        self.color_btn.set_tooltip_text("Color")
        if self.app.dark_mode:
            self.color_btn.set_rgba(Gdk.RGBA(1, 1, 1, 1))
        else:
            self.color_btn.set_rgba(Gdk.RGBA(0, 0, 0, 1))
        self.color_btn.connect("color-set", self.on_color_set)
        self.color_btn.get_style_context().add_class("color-button")
        self.sidebar.pack_start(self.color_btn, False, False, 0)

        # Clear canvas button with icon
        self.clear_btn = self.create_icon_button("larger-brush-symbolic.svg", "Clear Canvas")
        self.clear_btn.connect("clicked", self.on_clear)
        self.sidebar.pack_start(self.clear_btn, False, False, 0)

        sidebar_container.pack_start(self.sidebar, False, False, 0)
        overlay.add_overlay(sidebar_container)

    def create_size_popover(self):
        """Create the brush size popover."""
        self.size_popover = Gtk.Popover()
        self.size_popover.get_style_context().add_class("size-popover")

        size_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        size_box.set_margin_top(10)
        size_box.set_margin_bottom(10)
        size_box.set_margin_start(10)
        size_box.set_margin_end(10)

        self.size_label = Gtk.Label(label="Brush Size: 3")
        size_box.pack_start(self.size_label, False, False, 0)

        self.size_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 50, 1)
        self.size_scale.set_value(3)
        self.size_scale.set_size_request(150, -1)
        self.size_scale.connect("value-changed", self.on_brush_size_changed)
        size_box.pack_start(self.size_scale, False, False, 0)

        self.size_popover.add(size_box)
        size_box.show_all()

    def create_shapes_popover(self):
        """Create the shapes selection popover."""
        self.shapes_popover = Gtk.Popover()
        self.shapes_popover.set_relative_to(self.shapes_btn)

        shapes_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        shapes_box.get_style_context().add_class("shape-menu")
        shapes_box.set_margin_top(8)
        shapes_box.set_margin_bottom(8)
        shapes_box.set_margin_start(8)
        shapes_box.set_margin_end(8)

        # Shape type buttons with icons
        self.shape_buttons = {}
        shape_types = [
            ('rect', 'Rectangle', 'figure/box-outline-symbolic.svg'),
            ('circle', 'Circle', 'figure/circle-outline-thick-symbolic.svg'),
            ('triangle', 'Triangle', None),
            ('arrow', 'Arrow', None)
        ]

        for shape_type, tooltip, icon_file in shape_types:
            btn = Gtk.Button()
            btn.set_tooltip_text(tooltip)

            if icon_file:
                pixbuf = self.load_icon_white(icon_file)
                if pixbuf:
                    image = Gtk.Image.new_from_pixbuf(pixbuf)
                    btn.set_image(image)
                    btn.set_always_show_image(True)
                else:
                    btn.set_label(tooltip[:2].upper())
            else:
                btn.set_label(tooltip[:2].upper())

            btn.connect("clicked", self.on_select_shape_type, shape_type)
            shapes_box.pack_start(btn, False, False, 0)
            self.shape_buttons[shape_type] = btn

        self.shape_buttons['rect'].get_style_context().add_class("active")

        self.shapes_popover.add(shapes_box)
        shapes_box.show_all()

    def create_burger_menu(self, overlay):
        """Create the burger menu button."""
        menu_btn = Gtk.MenuButton()
        menu_btn.set_halign(Gtk.Align.END)
        menu_btn.set_valign(Gtk.Align.START)
        menu_btn.set_margin_end(15)
        menu_btn.set_margin_top(15)
        menu_btn.get_style_context().add_class("menu-button")

        # Set menu icon (white)
        menu_pixbuf = self.load_icon_white("menu-symbolic.svg")
        if menu_pixbuf:
            menu_image = Gtk.Image.new_from_pixbuf(menu_pixbuf)
            menu_btn.set_image(menu_image)

        # Menu popup
        menu = Gtk.Menu()

        # Save board
        save_item = Gtk.MenuItem(label="Save")
        save_item.connect("activate", self.on_save_board)
        menu.append(save_item)

        # Toggle sidebar
        toggle_sidebar_item = Gtk.MenuItem(label="Toggle Sidebar")
        toggle_sidebar_item.connect("activate", self.on_toggle_sidebar)
        menu.append(toggle_sidebar_item)

        # Back to main menu
        back_item = Gtk.MenuItem(label="Back to Menu")
        back_item.connect("activate", self.on_back_to_menu)
        menu.append(back_item)

        # About
        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self.on_about)
        menu.append(about_item)

        menu.show_all()
        menu_btn.set_popup(menu)

        overlay.add_overlay(menu_btn)

    def get_icon_path(self, icon_name):
        """Get the full path to an icon file."""
        return os.path.join(self.script_dir, "img", icon_name)

    def load_icon_white(self, icon_name, size=24):
        """Load an icon and make it white."""
        icon_path = self.get_icon_path(icon_name)
        if os.path.exists(icon_path):
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, size, size)
                # Make icon white by modifying pixel data
                pixbuf = pixbuf.copy()  # Make a mutable copy
                pixels = pixbuf.get_pixels()
                n_channels = pixbuf.get_n_channels()
                rowstride = pixbuf.get_rowstride()
                width = pixbuf.get_width()
                height = pixbuf.get_height()

                # Create new pixel data with white color
                new_pixels = bytearray(pixels)
                for y in range(height):
                    for x in range(width):
                        idx = y * rowstride + x * n_channels
                        # Keep alpha, set RGB to white
                        if n_channels >= 3:
                            new_pixels[idx] = 255      # R
                            new_pixels[idx + 1] = 255  # G
                            new_pixels[idx + 2] = 255  # B

                # Create new pixbuf from modified data
                new_pixbuf = GdkPixbuf.Pixbuf.new_from_data(
                    bytes(new_pixels),
                    pixbuf.get_colorspace(),
                    pixbuf.get_has_alpha(),
                    pixbuf.get_bits_per_sample(),
                    width,
                    height,
                    rowstride
                )
                return new_pixbuf
            except Exception:
                pass
        return None

    def create_icon_button(self, icon_name, tooltip):
        """Create a button with an icon from the img folder."""
        button = Gtk.Button()
        button.set_tooltip_text(tooltip)

        pixbuf = self.load_icon_white(icon_name)
        if pixbuf:
            image = Gtk.Image.new_from_pixbuf(pixbuf)
            button.set_image(image)
            button.set_always_show_image(True)
        else:
            button.set_label(tooltip[:3])

        button.set_relief(Gtk.ReliefStyle.NONE)
        return button

    def on_brush_button_press(self, button, event):
        """Handle brush button press - right click shows size popover."""
        if event.button == 3:  # Right click
            self.size_popover.set_relative_to(button)
            self.size_popover.popup()
            return True
        return False

    def on_eraser_button_press(self, button, event):
        """Handle eraser button press - right click shows size popover."""
        if event.button == 3:  # Right click
            self.size_popover.set_relative_to(button)
            self.size_popover.popup()
            return True
        return False

    def on_select_brush(self, button):
        """Select brush tool."""
        self.app.current_tool = 'brush'
        self.app.eraser_mode = False
        self.update_tool_buttons()

    def on_toggle_eraser(self, button):
        """Toggle eraser mode."""
        self.app.eraser_mode = not self.app.eraser_mode
        if self.app.eraser_mode:
            self.app.current_tool = 'brush'
        self.update_tool_buttons()

    def on_select_shape(self, button):
        """Select shape tool."""
        self.app.current_tool = 'shape'
        self.app.eraser_mode = False
        self.update_tool_buttons()

    def on_select_shape_type(self, button, shape_type):
        """Select a specific shape type."""
        self.app.current_shape_type = shape_type
        self.app.current_tool = 'shape'
        self.app.eraser_mode = False

        # Update shape button states
        for st, btn in self.shape_buttons.items():
            if st == shape_type:
                btn.get_style_context().add_class("active")
            else:
                btn.get_style_context().remove_class("active")

        self.update_tool_buttons()
        self.shapes_popover.popdown()

    def on_select_text(self, button):
        """Select text tool."""
        self.app.current_tool = 'text'
        self.app.eraser_mode = False
        self.update_tool_buttons()

    def update_tool_buttons(self):
        """Update the visual state of tool buttons."""
        # Reset all buttons
        self.brush_btn.get_style_context().remove_class("active")
        self.eraser_btn.get_style_context().remove_class("active")
        self.shapes_btn.get_style_context().remove_class("active")
        self.text_btn.get_style_context().remove_class("active")

        # Set active button
        if self.app.eraser_mode:
            self.eraser_btn.get_style_context().add_class("active")
        elif self.app.current_tool == 'brush':
            self.brush_btn.get_style_context().add_class("active")
        elif self.app.current_tool == 'shape':
            self.shapes_btn.get_style_context().add_class("active")
        elif self.app.current_tool == 'text':
            self.text_btn.get_style_context().add_class("active")

    def on_color_set(self, color_button):
        """Handle color picker color change."""
        rgba = color_button.get_rgba()
        self.app.brush_color = (rgba.red, rgba.green, rgba.blue)

    def on_brush_size_changed(self, scale):
        """Handle brush size change."""
        size = int(scale.get_value())
        if self.app.board:
            self.app.board.brush_size = size
        self.size_label.set_text(f"Brush Size: {size}")

    def on_clear(self, button):
        """Clear the canvas with confirmation."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Clear Canvas?"
        )
        dialog.format_secondary_text("This will remove all drawings. This action cannot be undone.")

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES and self.app.board:
            self.app.board.clear()

    def on_save_board(self, item):
        """Save the current board."""
        if self.app.board:
            data = self.app.board.get_board_data()
            data['dark_mode'] = self.app.dark_mode
            data['bg_color'] = self.app.bg_color
            data['brush_color'] = self.app.brush_color

            filepath = os.path.join(self.save_dir, f"{self.board_name}.json")

            # Ensure save directory exists
            if not os.path.exists(self.save_dir):
                os.makedirs(self.save_dir)

            with open(filepath, 'w') as f:
                json.dump(data, f)

            # Show confirmation
            dialog = Gtk.MessageDialog(
                transient_for=self,
                flags=0,
                message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK,
                text="Board Saved"
            )
            dialog.format_secondary_text(f"Board saved as '{self.board_name}'")
            dialog.run()
            dialog.destroy()

    def load_board(self):
        """Load board data from file."""
        filepath = os.path.join(self.save_dir, f"{self.board_name}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)

                self.app.dark_mode = data.get('dark_mode', False)
                self.app.bg_color = tuple(data.get('bg_color', (1.0, 1.0, 1.0)))
                self.app.brush_color = tuple(data.get('brush_color', (0.0, 0.0, 0.0)))

                if self.app.board:
                    self.app.board.load_board_data(data)
            except Exception as e:
                print(f"Failed to load board: {e}")

    def on_toggle_sidebar(self, item):
        """Toggle sidebar visibility."""
        if self.sidebar.get_visible():
            self.sidebar.hide()
        else:
            self.sidebar.show()

    def on_back_to_menu(self, item):
        """Go back to main menu."""
        self.destroy()
        self.main_menu.refresh_boards()
        self.main_menu.show_all()

    def on_about(self, item):
        """Show about dialog."""
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Aboard Whiteboard"
        )
        dialog.format_secondary_text(
            "A simple interactive whiteboard application.\n\n"
            "Controls:\n"
            "- Left click: Draw/Place\n"
            "- Right click + drag: Pan\n"
            "- Right click on Brush/Eraser: Size\n"
            "- Mouse wheel: Zoom\n"
            "- Ctrl+V: Paste image\n"
            "- Drag & drop: Add image\n"
            "- Use toolbar for tools"
        )
        dialog.run()
        dialog.destroy()

    def on_key_press(self, widget, event):
        """Handle key press events for paste functionality."""
        # Check for Ctrl+V
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            if event.keyval == Gdk.KEY_v or event.keyval == Gdk.KEY_V:
                self.paste_from_clipboard()
                return Gdk.EVENT_STOP
        return Gdk.EVENT_PROPAGATE

    def paste_from_clipboard(self):
        """Paste image from clipboard."""
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

        # Try to get image from clipboard
        pixbuf = clipboard.wait_for_image()
        if pixbuf:
            # Get center of visible area in world coordinates
            if self.app.board:
                alloc = self.app.board.get_allocation()
                center_x, center_y = self.app.board.screen_to_world(alloc.width / 2, alloc.height / 2)
                self.app.board.add_image(pixbuf, center_x - pixbuf.get_width() / 2, center_y - pixbuf.get_height() / 2)

    def on_drag_data_received(self, widget, drag_context, x, y, data, info, time):
        """Handle dropped files."""
        if data and data.get_uris():
            for uri in data.get_uris():
                # Convert URI to file path
                if uri.startswith("file://"):
                    filepath = uri[7:]
                    # URL decode the path
                    import urllib.parse
                    filepath = urllib.parse.unquote(filepath)

                    try:
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file(filepath)
                        if pixbuf:
                            wx, wy = self.app.board.screen_to_world(x, y)
                            self.app.board.add_image(pixbuf, wx, wy)
                    except Exception as e:
                        print(f"Failed to load image: {e}")

    def on_close(self, widget, event):
        """Handle window close."""
        self.main_menu.show_all()
        return False


class WhiteboardApp:
    """Main application class."""
    def __init__(self):
        self.bg_color = (1.0, 1.0, 1.0)
        self.brush_color = (0.0, 0.0, 0.0)
        self.board = None
        self.dark_mode = False
        self.eraser_mode = False
        self.sidebar_visible = True
        self.current_tool = 'brush'  # 'brush', 'shape', 'text'
        self.current_shape_type = 'rect'  # 'rect', 'circle', 'triangle', 'arrow'

    def run(self):
        """Run the application."""
        self.main_menu = MainMenuWindow(self)
        Gtk.main()

    def open_whiteboard(self, main_menu, board_name, dark_mode=False, is_new=True):
        """Open the whiteboard editor window."""
        WhiteboardWindow(self, main_menu, board_name, dark_mode=dark_mode, is_new=is_new)

    def show_text_input_dialog(self, x, y):
        """Show a dialog to input text."""
        # Get the active window
        active_window = None
        for window in Gtk.Window.list_toplevels():
            if window.is_active():
                active_window = window
                break

        dialog = Gtk.Dialog(
            title="Enter Text",
            transient_for=active_window,
            flags=0
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OK, Gtk.ResponseType.OK
        )

        content = dialog.get_content_area()
        content.set_margin_top(10)
        content.set_margin_bottom(10)
        content.set_margin_start(10)
        content.set_margin_end(10)

        entry = Gtk.Entry()
        entry.set_placeholder_text("Enter text here...")
        entry.set_width_chars(30)
        entry.connect("activate", lambda e: dialog.response(Gtk.ResponseType.OK))
        content.pack_start(entry, False, False, 0)

        dialog.show_all()
        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            text = entry.get_text()
            if self.board:
                self.board.add_text(text, x, y)

        dialog.destroy()


if __name__ == "__main__":
    app = WhiteboardApp()
    app.run()
