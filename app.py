import os
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, render_template, send_from_directory
from flask_cors import CORS
import requests
from twilio.rest import Client
from database import get_db, init_db
import uuid
import sqlite3
import csv
import io

app = Flask(__name__, template_folder='templates')
CORS(app, resources={r"/api/*": {"origins": "*"}})

UPLOAD_FOLDER = 'static/uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

init_db()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/static/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# --- AUTH ---
@app.route('/api/login', methods=['POST', 'OPTIONS'])
def login():
    if request.method == 'OPTIONS': return jsonify({"success": True}), 200
    data = request.json
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=? AND password=?",
                        (data['email'], data['password'])).fetchone()
    conn.close()
    if user:
        return jsonify({"success": True, "user": dict(user)})
    return jsonify({"success": False, "message": "Invalid credentials"}), 401


# --- EVENTS (Create, Update, Delete) ---
@app.route('/api/events', methods=['GET', 'POST'])
def manage_events():
    conn = get_db()
    if request.method == 'GET':
        events = conn.execute("SELECT * FROM events").fetchall()
        conn.close()
        return jsonify([dict(e) for e in events])
    else:
        # Create Event
        data = request.form
        invite_image_path = None

        if 'invite_image' in request.files:
            file = request.files['invite_image']
            if file.filename != '':
                filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                invite_image_path = f"/static/uploads/{filename}"

        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO events (title, date, time, location, hall, host, event_type, invite_image) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data.get('title'), data.get('date'), data.get('time'), data.get('location'), data.get('hall'),
             data.get('host'), data.get('event_type'), invite_image_path)
        )
        conn.commit()
        new_id = cursor.lastrowid
        conn.close()
        return jsonify({"success": True, "id": new_id})


@app.route('/api/events/<int:event_id>', methods=['PUT', 'DELETE'])
def edit_event(event_id):
    conn = get_db()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM guests WHERE event_id=?", (event_id,))
        conn.execute("DELETE FROM events WHERE id=?", (event_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})

    elif request.method == 'PUT':
        data = request.form
        # Keep existing image unless a new one is uploaded
        current_img = conn.execute("SELECT invite_image FROM events WHERE id=?", (event_id,)).fetchone()
        invite_image_path = current_img['invite_image'] if current_img else None

        if 'invite_image' in request.files:
            file = request.files['invite_image']
            if file.filename != '':
                filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}")
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                invite_image_path = f"/static/uploads/{filename}"

        conn.execute(
            "UPDATE events SET title=?, date=?, time=?, location=?, hall=?, host=?, event_type=?, invite_image=? WHERE id=?",
            (data.get('title'), data.get('date'), data.get('time'), data.get('location'), data.get('hall'),
             data.get('host'), data.get('event_type'), invite_image_path, event_id)
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})


# --- PUBLIC STATS FOR CUSTOMER PORTAL ---
@app.route('/api/public_stats', methods=['GET'])
def public_stats():
    conn = get_db()
    total_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    total_guests = conn.execute("SELECT COUNT(*) FROM guests").fetchone()[0]
    total_checked_in = conn.execute("SELECT COUNT(*) FROM guests WHERE checked_in=1").fetchone()[0]
    conn.close()
    return jsonify({
        "events": total_events,
        "guests": total_guests,
        "checked_in": total_checked_in
    })

# --- GUESTS (Manual, Bulk, Edit, Delete) ---
@app.route('/api/guests/<int:event_id>', methods=['GET', 'POST'])
def manage_guests(event_id):
    conn = get_db()
    if request.method == 'GET':
        guests = conn.execute("SELECT * FROM guests WHERE event_id=?", (event_id,)).fetchall()
        conn.close()
        return jsonify([dict(g) for g in guests])
    else:
        # Single Guest
        data = request.json
        ticket_hash = f"HASH-{uuid.uuid4().hex[:8].upper()}"
        conn.execute("INSERT INTO guests (event_id, name, phone, channel, ticket_hash) VALUES (?, ?, ?, ?, ?)",
                     (event_id, data['name'], data['phone'], data['channel'], ticket_hash))
        conn.commit()
        conn.close()
        return jsonify({"success": True})


@app.route('/api/guests/single/<int:guest_id>', methods=['PUT', 'DELETE'])
def edit_single_guest(guest_id):
    conn = get_db()
    if request.method == 'DELETE':
        conn.execute("DELETE FROM guests WHERE id=?", (guest_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})

    elif request.method == 'PUT':
        data = request.json
        conn.execute("UPDATE guests SET name=?, phone=?, channel=? WHERE id=?",
                     (data['name'], data['phone'], data['channel'], guest_id))
        conn.commit()
        conn.close()
        return jsonify({"success": True})

# --- WHATSAPP DISPATCH WITH IMAGE SUPPORT ---
@app.route('/api/whatsapp_webhook', methods=['POST'])
def whatsapp_webhook():
    # Simulates receiving a WhatsApp message from a guest
    data = request.json
    phone = data.get('phone')
    reply = data.get('message', '').strip().upper()  # "YES" or "NO"

    conn = get_db()
    guest = conn.execute("SELECT * FROM guests WHERE phone LIKE ?", (f"%{phone}%",)).fetchone()

    if guest:
        status = 'Accepted' if reply in ['YES', 'ACCEPT', 'NDIO'] else 'Declined' if reply in ['NO', 'DECLINE',
                                                                                               'HAPANA'] else 'Pending'
        conn.execute("UPDATE guests SET status=? WHERE id=?", (status, guest['id']))
        conn.commit()
        conn.close()
        return jsonify({"success": True, "status": status})

    conn.close()
    return jsonify({"success": False, "message": "Guest not found"}), 404


@app.route('/api/dispatch', methods=['POST'])
def dispatch_messages():
    data = request.json
    guest_ids = data.get('guest_ids', [])
    event_id = data.get('event_id')
    msg_type = data.get('type', 'invite')  # 'invite' or 'reminder'
    custom_message = data.get('custom_message', '')  # Receive the drafted message

    if not guest_ids or not event_id:
        return jsonify({"success": False, "message": "Missing guest IDs or Event ID"}), 400

    conn = get_db()

    # 1. Update Database Flags
    placeholders = ','.join('?' * len(guest_ids))
    if msg_type == 'invite':
        conn.execute(f"UPDATE guests SET invite_sent=1 WHERE id IN ({placeholders})", guest_ids)
    else:
        conn.execute(f"UPDATE guests SET reminder_sent=1 WHERE id IN ({placeholders})", guest_ids)
    conn.commit()

    # 2. Fetch Event and Guest Data
    event = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    recipients = conn.execute(f"SELECT name, phone, channel, ticket_hash FROM guests WHERE id IN ({placeholders})",
                              guest_ids).fetchall()
    conn.close()

    if not event:
        return jsonify({"success": False, "message": "Event not found"}), 404

    # 3. Setup API Credentials
    TWILIO_SID = os.environ.get('TWILIO_ACCOUNT_SID')
    TWILIO_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN')
    TWILIO_FROM = os.environ.get('TWILIO_PHONE_NUMBER')

    WA_TOKEN = os.environ.get('WHATSAPP_TOKEN')
    WA_PHONE_ID = os.environ.get('WHATSAPP_PHONE_ID')

    BASE_URL = os.environ.get('BASE_URL', 'http://mwalikaji.com')

    success_count = 0
    failed_count = 0

    # 4. Loop through recipients and send
    for r in recipients:
        phone = r['phone']
        name = r['name']
        channel = r['channel']

        # Default message if host didn't type anything
        if not custom_message.strip():
            message_body = f"🎉 Invitation to {event['title']}!\nDear {name}, you are invited.\nPass Code: {r['ticket_hash']}"
        else:
            # Replace placeholders with actual guest/event data
            message_body = custom_message.replace("{name}", name) \
                .replace("{event_title}", event['title']) \
                .replace("{date}", event['date']) \
                .replace("{time}", event['time']) \
                .replace("{location}", f"{event['location']} {event['hall'] or ''}") \
                .replace("{hash}", r['ticket_hash'])

        try:
            # --- SEND VIA SMS (TWILIO) ---
            if channel == 'sms' and TWILIO_SID and TWILIO_TOKEN:
                client = Client(TWILIO_SID, TWILIO_TOKEN)
                client.messages.create(body=message_body, from_=TWILIO_FROM, to=phone)
                success_count += 1

            # --- SEND VIA WHATSAPP (META) ---
            elif channel == 'whatsapp' and WA_TOKEN and WA_PHONE_ID:
                url = f"https://graph.facebook.com/v18.0/{WA_PHONE_ID}/messages"
                headers = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}

                if event['invite_image']:
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "image",
                        "image": {"link": f"{BASE_URL}{event['invite_image']}", "caption": message_body}
                    }
                else:
                    payload = {
                        "messaging_product": "whatsapp",
                        "to": phone,
                        "type": "text",
                        "text": {"body": message_body}
                    }

                response = requests.post(url, headers=headers, json=payload)
                if response.status_code == 200:
                    success_count += 1
                else:
                    print(f"WhatsApp Error: {response.text}")
                    failed_count += 1

            # --- SIMULATION ---
            else:
                print(f"[SIMULATION] To: {name} ({phone}) via {channel.upper()}")
                print(f"Message: {message_body}")
                success_count += 1

        except Exception as e:
            print(f"Failed to send to {name}: {e}")
            failed_count += 1

    return jsonify({
        "success": True,
        "message": f"Dispatched {success_count} messages. {failed_count} failed."
    })


# --- USER MANAGEMENT (Super Admin Only) ---
@app.route('/api/users', methods=['GET', 'POST'])
def manage_users():
    conn = get_db()
    if request.method == 'GET':
        # Fetch all users (excluding passwords for security)
        users = conn.execute("SELECT id, name, email, role FROM users").fetchall()
        conn.close()
        return jsonify([dict(u) for u in users])

    elif request.method == 'POST':
        data = request.json
        try:
            conn.execute("INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                         (data['name'], data['email'], data['password'], data['role']))
            conn.commit()
            conn.close()
            return jsonify({"success": True})
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"success": False, "message": "Email already exists"}), 400
        except Exception as e:
            conn.close()
            return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/checkin', methods=['POST'])
def checkin():
    data = request.json
    conn = get_db()
    guest = conn.execute("SELECT * FROM guests WHERE ticket_hash=?", (data['ticket_hash'],)).fetchone()
    if not guest:
        conn.close()
        return jsonify({"success": False, "message": "Invalid Ticket"}), 404
    if guest['checked_in']:
        conn.close()
        return jsonify({"success": False, "message": "Already Checked In!"}), 400
    conn.execute("UPDATE guests SET checked_in=1 WHERE id=?", (guest['id'],))
    conn.commit()
    conn.close()
    return jsonify({"success": True, "guest": dict(guest)})


if __name__ == '__main__':
    app.run(debug=True)