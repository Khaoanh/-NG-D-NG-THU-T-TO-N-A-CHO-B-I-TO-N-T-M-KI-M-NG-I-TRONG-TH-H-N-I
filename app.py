from flask import Flask, request, jsonify, send_from_directory, make_response
from flask_cors import CORS
import sqlite3
import requests
import heapq
import math
from datetime import datetime
import json
import os
import random

app = Flask(__name__)
# Cho phép CORS từ tất cả các nguồn
CORS(app)

# Khởi tạo MapTiler API key - Sử dụng biến môi trường hoặc cấu hình riêng
MAPTILER_API_KEY = 'R1x1XIEN12s6f4qM13Er'

# Đảm bảo tất cả API trả về JSON
@app.after_request
def add_header(response):
    # Chỉ thêm header cho các API endpoint, không phải cho tệp tĩnh
    if request.path.startswith('/directions') or request.path.startswith('/saved_directions') or request.path.startswith('/delete_directions'):
        response.headers['Content-Type'] = 'application/json'
    return response

# Khởi tạo cơ sở dữ liệu
def init_db():
    conn = sqlite3.connect('directions.db')
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS directions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        start TEXT NOT NULL,
        goal TEXT NOT NULL,
        travel_mode TEXT NOT NULL,
        distance TEXT NOT NULL,
        duration TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    conn.commit()
    conn.close()

init_db()

# Hàm heuristic khoảng cách Euclid
def heuristic(a, b):
    """Tính khoảng cách Euclid giữa 2 điểm"""
    return math.sqrt((a[0] - b[0])**2 + (a[1] - b[1])**2)

# Thuật toán A*
def a_star(start, goal, graph):
    """Tìm đường đi ngắn nhất từ start đến goal sử dụng thuật toán A*"""
    if not graph:  # Kiểm tra nếu đồ thị rỗng
        print("Đồ thị rỗng, trả về đường đi trực tiếp")
        return [start, goal]
        
    # Chuyển đổi start và goal thành tuple nếu chúng là list
    if isinstance(start, list):
        start = tuple(start)
    if isinstance(goal, list):
        goal = tuple(goal)
    
    # Kiểm tra xem start và goal có trong đồ thị không
    if start not in graph:
        print(f"Điểm bắt đầu {start} không có trong đồ thị, trả về đường đi trực tiếp")
        return [list(start), list(goal)]
        
    open_set = []
    heapq.heappush(open_set, (0, start))
    came_from = {}
    g_score = {start: 0}
    f_score = {start: heuristic(start, goal)}
    
    while open_set:
        _, current = heapq.heappop(open_set)
        
        if current == goal:
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start)
            path.reverse()
            return [list(point) for point in path]  # Chuyển đổi tuple thành list
        
        if current not in graph:
            continue
            
        for neighbor, cost in graph[current]:
            tentative_g_score = g_score[current] + cost
            
            if neighbor not in g_score or tentative_g_score < g_score[neighbor]:
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g_score
                f_score[neighbor] = tentative_g_score + heuristic(neighbor, goal)
                if not any(neighbor == item[1] for item in open_set):
                    heapq.heappush(open_set, (f_score[neighbor], neighbor))
    
    print("Không tìm thấy đường đi, trả về đường đi trực tiếp")
    return [list(start), list(goal)]

# Hàm để lấy tọa độ từ địa chỉ sử dụng MapTiler Geocoding API
def geocode_address(address):
    """Chuyển đổi địa chỉ thành tọa độ [lat, lng] sử dụng MapTiler Geocoding API"""
    # Thêm "Hà Nội" vào địa chỉ nếu không có để tăng độ chính xác
    if "hà nội" not in address.lower():
        search_address = f"{address}, Hà Nội, Việt Nam"
    else:
        search_address = f"{address}, Việt Nam"
        
    try:
        url = f"https://api.maptiler.com/geocoding/{search_address}.json?key={MAPTILER_API_KEY}"
        response = requests.get(url, timeout=5)  # Thêm timeout
        
        if response.status_code != 200:
            print(f"Geocoding API trả về mã lỗi: {response.status_code}")
            print(f"Nội dung lỗi: {response.text}")
            return None
            
        data = response.json()
        
        if 'features' in data and len(data['features']) > 0:
            coordinates = data['features'][0]['geometry']['coordinates']
            # MapTiler trả về [lng, lat], chúng ta cần chuyển về [lat, lng]
            return [coordinates[1], coordinates[0]]
        else:
            print(f"Không tìm thấy địa điểm: {address}")
            return None
    except Exception as e:
        print(f"Lỗi khi gọi Geocoding API: {str(e)}")
        return None

# Hàm để tạo đường đi trực tiếp giữa hai điểm
def create_direct_path(start_coord, goal_coord):
    """Tạo đường đi trực tiếp giữa hai điểm với thông tin khoảng cách và thời gian"""
    # Tính khoảng cách Euclid giữa hai điểm (km)
    distance_km = math.sqrt((start_coord[0] - goal_coord[0])**2 + (start_coord[1] - goal_coord[1])**2) * 111  # 1 độ ~ 111km
    
    # Ước tính thời gian (giả sử tốc độ trung bình 40 km/h)
    duration_hours = distance_km / 40
    
    if distance_km < 1:
        distance = f"{int(distance_km * 1000)} m"
    else:
        distance = f"{distance_km:.1f} km"
        
    if duration_hours < 1/60:
        duration = f"{int(duration_hours * 3600)} giây"
    elif duration_hours < 1:
        duration = f"{int(duration_hours * 60)} phút"
    else:
        hours = int(duration_hours)
        minutes = int((duration_hours - hours) * 60)
        duration = f"{hours} giờ {minutes} phút"
        
    return {
        'path': [start_coord, goal_coord],
        'distance': distance,
        'duration': duration
    }

# Tạo đồ thị từ điểm bắt đầu và kết thúc với các điểm trung gian
def create_graph_from_points(start_coord, goal_coord, num_intermediate=8):
    """Tạo đồ thị từ điểm bắt đầu và kết thúc với các điểm trung gian ngẫu nhiên"""
    graph = {}
    
    # Thêm điểm bắt đầu và kết thúc
    start_tuple = tuple(start_coord)
    goal_tuple = tuple(goal_coord)
    
    # Tạo các điểm trung gian dọc theo đường thẳng giữa start và goal
    points = [start_tuple]
    
    # Tạo các điểm trung gian
    for i in range(1, num_intermediate + 1):
        ratio = i / (num_intermediate + 1)
        lat = start_coord[0] + ratio * (goal_coord[0] - start_coord[0])
        lng = start_coord[1] + ratio * (goal_coord[1] - start_coord[1])
        
        # Thêm một chút nhiễu ngẫu nhiên để tạo đường đi không thẳng
        lat_noise = (random.random() - 0.5) * 0.005  # Khoảng ±0.005 độ
        lng_noise = (random.random() - 0.5) * 0.005
        
        point = (lat + lat_noise, lng + lng_noise)
        points.append(point)
    
    points.append(goal_tuple)
    
    # Tạo đồ thị từ các điểm
    for i in range(len(points)):
        current = points[i]
        if current not in graph:
            graph[current] = []
        
        # Kết nối với các điểm lân cận
        for j in range(len(points)):
            if i != j:
                neighbor = points[j]
                distance = heuristic(current, neighbor)
                
                # Chỉ kết nối với các điểm gần
                if distance < 0.05:  # Khoảng cách tối đa để kết nối
                    graph[current].append((neighbor, distance))
    
    return graph

# API endpoint để lấy chỉ đường
@app.route('/directions', methods=['GET'])
def directions():
    start = request.args.get('start')  # Lấy địa điểm bắt đầu từ tham số URL
    goal = request.args.get('goal')  # Lấy địa điểm đích từ tham số URL
    travelMode = request.args.get('travelMode')  # Lấy phương thức di chuyển
    
    print(f"Tìm đường từ {start} đến {goal} bằng {travelMode}")

    try:
        # Chuyển đổi địa chỉ thành tọa độ
        start_coord = geocode_address(start)
        goal_coord = geocode_address(goal)
        
        if not start_coord:
            response_data = {
                'error': f'Không thể tìm thấy địa điểm: {start}',
                'success': False,
                'fallback': True,
                'distance': '0 km',
                'duration': '0 phút'
            }
            print(f"Phản hồi JSON: {json.dumps(response_data)}")
            response = make_response(jsonify(response_data), 200)
            response.headers['Content-Type'] = 'application/json'
            return response
            
        if not goal_coord:
            response_data = {
                'error': f'Không thể tìm thấy địa điểm: {goal}',
                'success': False,
                'fallback': True,
                'distance': '0 km',
                'duration': '0 phút'
            }
            print(f"Phản hồi JSON: {json.dumps(response_data)}")
            response = make_response(jsonify(response_data), 200)
            response.headers['Content-Type'] = 'application/json'
            return response
            
        print(f"Tọa độ điểm bắt đầu: {start_coord}")
        print(f"Tọa độ điểm kết thúc: {goal_coord}")
        
        # Tạo đồ thị từ điểm bắt đầu và kết thúc
        graph = create_graph_from_points(start_coord, goal_coord)
        
        # Tìm đường đi bằng thuật toán A*
        path = a_star(start_coord, goal_coord, graph)
        
        # Khởi tạo biến distance và duration
        distance = ""
        duration = ""
        
        if not path or len(path) < 2:
            print("Không tìm được đường đi bằng A*, sử dụng đường đi trực tiếp")
            # Tạo đường đi trực tiếp
            route_data = create_direct_path(start_coord, goal_coord)
            path = route_data['path']
            distance = route_data['distance']
            duration = route_data['duration']
        else:
            print(f"Tìm thấy đường đi bằng A* với {len(path)} điểm")
            # Tính khoảng cách và thời gian
            total_distance = 0
            for i in range(len(path) - 1):
                total_distance += heuristic(path[i], path[i + 1])
            
            # Chuyển đổi sang km
            distance_km = total_distance * 111
            
            # Ước tính thời gian (giả sử tốc độ trung bình 40 km/h)
            duration_hours = distance_km / 40
            
            if distance_km < 1:
                distance = f"{int(distance_km * 1000)} m"
            else:
                distance = f"{distance_km:.1f} km"
                
            if duration_hours < 1/60:
                duration = f"{int(duration_hours * 3600)} giây"
            elif duration_hours < 1:
                duration = f"{int(duration_hours * 60)} phút"
            else:
                hours = int(duration_hours)
                minutes = int((duration_hours - hours) * 60)
                duration = f"{hours} giờ {minutes} phút"
        
        # Đảm bảo distance và duration không rỗng
        if not distance:
            distance = "0 km"
        if not duration:
            duration = "0 phút"
            
        # Lưu vào cơ sở dữ liệu
        save_to_db(start, goal, travelMode, distance, duration)
        
        response_data = {
            'distance': distance,
            'duration': duration,
            'path': path,
            'success': True,
            'fallback': False,
            'message': 'Tìm đường thành công bằng thuật toán A*'
        }
        
        print(f"Phản hồi JSON: {json.dumps(response_data)}")
        print(f"Khoảng cách: {distance}, Thời gian: {duration}")
        response = make_response(jsonify(response_data), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
        
    except Exception as e:
        import traceback
        print(f"Lỗi: {str(e)}")
        print(traceback.format_exc())
        response_data = {
            'error': str(e),
            'success': False,
            'fallback': True,
            'distance': '0 km',
            'duration': '0 phút',
            'path': [[21.0285, 105.8542], [21.0285, 105.8542]]  # Điểm mặc định ở Hà Nội
        }
        print(f"Phản hồi JSON lỗi: {json.dumps(response_data)}")
        response = make_response(jsonify(response_data), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

def save_to_db(start, goal, travel_mode, distance, duration):
    conn = sqlite3.connect('directions.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO directions (start, goal, travel_mode, distance, duration)
        VALUES (?, ?, ?, ?, ?)
    ''', (start, goal, travel_mode, distance, duration))
    conn.commit()
    conn.close()

# API endpoint để lấy lịch sử
@app.route('/saved_directions', methods=['GET'])
def saved_directions():
    conn = sqlite3.connect('directions.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM directions ORDER BY id DESC')  # Sắp xếp theo thứ tự mới nhất
    directions = cursor.fetchall()
    conn.close()
    
    response = make_response(jsonify(directions), 200)
    response.headers['Content-Type'] = 'application/json'
    return response

# API endpoint để xóa lịch sử
@app.route('/delete_directions/<int:id>', methods=['DELETE'])
def delete_directions(id):
    conn = sqlite3.connect('directions.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM directions WHERE id = ?', (id,))
    conn.commit()
    
    if cursor.rowcount > 0:
        conn.close()
        response = make_response(jsonify({'message': 'Xóa thành công!'}), 200)
        response.headers['Content-Type'] = 'application/json'
        return response
    else:
        conn.close()
        response = make_response(jsonify({'error': 'Không tìm thấy chỉ đường với ID này!'}), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

@app.route('/delete_all_directions', methods=['DELETE'])
def delete_all_directions():
    conn = sqlite3.connect('directions.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM directions')
    cursor.execute('DELETE FROM sqlite_sequence WHERE name="directions"')
    conn.commit()
    conn.close()
    
    response = make_response(jsonify({'message': 'Đã xóa tất cả dữ liệu thành công và ID đã được đặt lại!'}), 200)
    response.headers['Content-Type'] = 'application/json'
    return response

# Serve static files
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('.', path)

if __name__ == '__main__':
    app.static_folder = '.'
    app.run(debug=True)