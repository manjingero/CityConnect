import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, join_room, emit
from cities import cities  # assuming cities.py exports a list of cities in uppercase
import random
import os
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, async_mode='eventlet')

# Global storage for game room states.
rooms = {}

# List of accepted cities (all uppercase)
accepted_cities = cities

def initialize_room(room):
    """Initialize a new room with a 10x10 grid and place the starting word in the center.
       Then, update the room's expansion based on the starting word's bounding box."""
    starting_city = random.choice(accepted_cities)
    grid = {}
    grid_size = 10
    row = grid_size // 2
    start_col = (grid_size - len(starting_city)) // 2
    for i, letter in enumerate(starting_city):
        grid[(start_col + i, row)] = letter  # already uppercase

    # Calculate bounding box for the starting grid.
    xs = [pos[0] for pos in grid.keys()]
    ys = [pos[1] for pos in grid.keys()]
    width = max(xs) - min(xs) + 1
    height = max(ys) - min(ys) + 1
    largest_dim = max(width, height)
    base_dim = 10  # initial board is 10x10
    # +2 extra units to ensure the full word is visible.
    needed = largest_dim - base_dim + 2
    expansion = needed if needed > 0 else 0

    rooms[room] = {
        'grid': grid,
        'players': [],
        'player_activity': {},
        'scores': {},
        'turn_index': 0,
        'placed_cities': [starting_city],
        'starting_city': starting_city,
        'expansion': expansion,
        'last_activity': time.time()
    }

def format_grid(grid):
    """Convert grid keys (tuples) to strings for JSON transmission."""
    formatted = {}
    for pos, letter in grid.items():
        formatted[str(pos)] = letter
    return formatted

def get_word(board, pos, dx, dy):
    """
    Starting at pos, move backwards in direction (-dx,-dy) until an empty cell is found.
    Then, starting from that cell, move forward (dx,dy) collecting letters.
    Returns the contiguous word.
    """
    (x, y) = pos
    bx, by = x, y
    while (bx - dx, by - dy) in board:
        bx, by = bx - dx, by - dy
    word = ""
    cx, cy = bx, by
    while (cx, cy) in board:
        word += board[(cx, cy)]
        cx, cy = cx + dx, cy + dy
    return word

def compute_leaderboard(room_details):
    """Return a leaderboard list: each item is {'name': <player or 'User Left'>, 'score': <score>}."""
    leaderboard = []
    for user, score in room_details['scores'].items():
        name = user if user in room_details['players'] else "User Left"
        leaderboard.append({"name": name, "score": score})
    leaderboard.sort(key=lambda x: x['score'], reverse=True)
    return leaderboard

@app.route('/')
def index():
    # You can change this to render your index.html if needed.
    return render_template('index.html')

@app.route('/public_games')
def public_games():
    # Add a print statement for debugging (check your Passenger error log)
    print("public_games route was called")
    now = time.time()
    active_rooms = {room: details for room, details in rooms.items()
                    if (now - details['last_activity']) < 300 and len(details['players']) > 0}
    public_game_list = []
    for room, details in active_rooms.items():
        public_game_list.append({
            'room': room,
            'starting_city': details['starting_city'],
            'players': details['players'],
            'current_turn': details['players'][details['turn_index']] if details['players'] else "",
            'expansion': details['expansion'],
            'last_activity': details['last_activity']
        })
    return jsonify(public_game_list)

@socketio.on('enter_room')
def handle_enter_room(data):
    room = data.get('room')
    username = data.get('username')
    if not room or not username:
        emit('error', {'message': 'Room and username are required.'})
        return
    if room not in rooms:
        initialize_room(room)
    if username not in rooms[room]['players']:
        rooms[room]['players'].append(username)
    if username not in rooms[room]['scores']:
        rooms[room]['scores'][username] = 0
    rooms[room]['player_activity'][username] = time.time()
    rooms[room]['last_activity'] = time.time()
    join_room(room)
    print(f"{username} joined room {room}")
    leaderboard = compute_leaderboard(rooms[room])
    emit('room_update', {
        'room': room,
        'players': rooms[room]['players'],
        'starting_city': rooms[room]['starting_city'],
        'grid': format_grid(rooms[room]['grid']),
        'current_turn': rooms[room]['players'][rooms[room]['turn_index']],
        'expansion': rooms[room]['expansion'],
        'leaderboard': leaderboard
    }, room=room)

@socketio.on('new_move')
def handle_new_move(data):
    """
    Expected data:
      - room: room name
      - username: moving player
      - x, y: starting cell coordinate (cell clicked)
      - direction: 'up', 'down', 'right', or 'left'
      - city: full city name (string) to place letter-by-letter
    After simulating placement, every contiguous word along the primary axis and
    for each new letter's perpendicular axis (if length ≥ 2) must be valid.
    Score is computed as the number of intersections with existing letters.
    """
    room = data.get('room')
    username = data.get('username')
    city = data.get('city')
    direction = data.get('direction')
    start_x = data.get('x')
    start_y = data.get('y')

    if None in (room, username, city, direction, start_x, start_y):
        emit('error', {'message': 'Missing data for move.'})
        return

    city = city.strip().upper()
    if city not in accepted_cities:
        emit('error', {'message': f"{city} is not an accepted city."})
        return
    if city in rooms[room]['placed_cities']:
        emit('error', {'message': f"{city} has already been used."})
        return

    grid = rooms[room]['grid']
    L = len(city)
    new_positions = []
    if direction == 'up':
        for i in range(L):
            new_positions.append((start_x, start_y - i))
    elif direction == 'down':
        for i in range(L):
            new_positions.append((start_x, start_y + i))
    elif direction == 'right':
        for i in range(L):
            new_positions.append((start_x + i, start_y))
    elif direction == 'left':
        for i in range(L):
            new_positions.append((start_x - (L - 1) + i, start_y))
    else:
        emit('error', {'message': 'Invalid direction.'})
        return

    if not any(pos in grid for pos in new_positions):
        emit('error', {'message': 'Move must intersect at least one existing letter on the board.'})
        return

    for i, pos in enumerate(new_positions):
        if pos in grid and grid[pos].upper() != city[i]:
            emit('error', {'message': 'Letter mismatch at intersection.'})
            return

    # --- Scrabble–like validation ---
    new_grid = grid.copy()
    for i, pos in enumerate(new_positions):
        new_grid[pos] = city[i]

    if direction in ['left', 'right']:
        prim_dx, prim_dy = 1, 0
    elif direction in ['up', 'down']:
        prim_dx, prim_dy = 0, 1

    primary_cell = new_positions[-1] if direction == 'up' else new_positions[0]
    primary_word = get_word(new_grid, primary_cell, prim_dx, prim_dy)
    if len(primary_word) >= 2 and primary_word not in accepted_cities:
        emit('error', {'message': f"Primary word '{primary_word}' is not a valid city."})
        return

    if prim_dx == 1:
        perp_dx, perp_dy = 0, 1
    else:
        perp_dx, perp_dy = 1, 0

    for pos in new_positions:
        cross_word = get_word(new_grid, pos, perp_dx, perp_dy)
        if len(cross_word) >= 2 and cross_word not in accepted_cities:
            emit('error', {'message': f"Cross word '{cross_word}' at {pos} is not a valid city."})
            return
    # --- End validation ---

    new_tiles = sum(1 for pos in new_positions if pos not in grid)
    points = L - new_tiles

    for i, pos in enumerate(new_positions):
        grid[pos] = city[i]

    rooms[room]['scores'][username] += points
    rooms[room]['placed_cities'].append(city)
    rooms[room]['expansion'] += 1  # turn-based expansion increment
    rooms[room]['player_activity'][username] = time.time()
    rooms[room]['last_activity'] = time.time()

    if len(rooms[room]['players']) > 1:
        rooms[room]['turn_index'] = (rooms[room]['turn_index'] + 1) % len(rooms[room]['players'])
    next_turn = rooms[room]['players'][rooms[room]['turn_index']]

    # --- Adjust expansion based on bounding box ---
    all_positions = list(grid.keys())
    if all_positions:
        xs = [pos[0] for pos in all_positions]
        ys = [pos[1] for pos in all_positions]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max_x - min_x + 1
        height = max_y - min_y + 1
        largest_dim = max(width, height)
        base_dim = 10  # base dimension of initial board
        needed = largest_dim - base_dim + 1  # +1 extra unit to cover missing one letter
        if needed > rooms[room]['expansion']:
            rooms[room]['expansion'] = needed
    # --- End adjustment ---

    leaderboard = compute_leaderboard(rooms[room])

    emit('move_made', {
        'username': username,
        'city': city,
        'positions': new_positions,
        'points': points,
        'grid': format_grid(grid),
        'current_turn': next_turn,
        'expansion': rooms[room]['expansion'],
        'leaderboard': leaderboard
    }, room=room)

@socketio.on('error')
def error_handler(data):
    print("Error:", data)

def cleanup_inactive():
    """Background task: remove players inactive > 600 sec and delete rooms with no players > 5 min."""
    while True:
        now = time.time()
        rooms_to_delete = []
        for room, details in list(rooms.items()):
            removed = False
            for player in details['players'].copy():
                last_act = details['player_activity'].get(player, 0)
                if now - last_act > 600:
                    details['players'].remove(player)
                    details['player_activity'].pop(player, None)
                    print(f"Removed inactive player {player} from room {room}")
                    removed = True
            if removed:
                if details['turn_index'] >= len(details['players']):
                    details['turn_index'] = 0
                leaderboard = compute_leaderboard(details)
                socketio.emit('room_update', {
                    'room': room,
                    'players': details['players'],
                    'starting_city': details['starting_city'],
                    'grid': format_grid(details['grid']),
                    'current_turn': details['players'][details['turn_index']] if details['players'] else "",
                    'expansion': details['expansion'],
                    'leaderboard': leaderboard
                }, room=room)
            if not details['players'] and now - details['last_activity'] > 300:
                rooms_to_delete.append(room)
        for room in rooms_to_delete:
            print(f"Deleting room {room} due to inactivity.")
            del rooms[room]
        socketio.sleep(10)

socketio.start_background_task(cleanup_inactive)

if __name__ == '__main__':
    socketio.run(app, debug=True)