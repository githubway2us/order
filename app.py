from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash
)
import sqlite3
from datetime import datetime
import os
import hashlib
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ─── การตั้งค่าที่สำคัญ ────────────────────────────────────────────────
app.secret_key = os.environ.get("SECRET_KEY") or "super-secret-key-change-this-2025-geotran-manss-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"

app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False  # เปลี่ยนเป็น True เมื่อใช้ HTTPS
app.config['PERMANENT_SESSION_LIFETIME'] = 86400  # 1 วัน

# CSRF Protection
csrf = CSRFProtect(app)

@app.context_processor
def inject_csrf():
    return dict(csrf_token=generate_csrf)

# Database path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "database.db")

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        c = conn.cursor()

        # สินค้า
        c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT DEFAULT 'อื่นๆ'
        )
        """)
        try:
            c.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'อื่นๆ'")
        except sqlite3.OperationalError:
            pass

        # ผู้ใช้
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0,
            phone TEXT
        )
        """)

        # user_points
        c.execute("""
        CREATE TABLE IF NOT EXISTS user_points (
            user_id INTEGER PRIMARY KEY,
            available_points INTEGER DEFAULT 0,
            earned_points INTEGER DEFAULT 0,
            redeemed_points INTEGER DEFAULT 0,
            pending_points INTEGER DEFAULT 0,
            last_updated TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """)

        # redeemed_rewards
        c.execute("""
        CREATE TABLE IF NOT EXISTS redeemed_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            reward_name TEXT,
            points_used INTEGER,
            redeemed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """)

        # rewards
        c.execute("""
        CREATE TABLE IF NOT EXISTS rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            points_required INTEGER NOT NULL,
            stock INTEGER DEFAULT 999,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            image_url TEXT  -- เพิ่มบรรทัดนี้
        )
        """)
        try:
            c.execute("ALTER TABLE rewards ADD COLUMN image_url TEXT")
        except sqlite3.OperationalError:
            pass  # มีแล้ว ข้าม
        c.execute("SELECT COUNT(*) FROM rewards")
        if c.fetchone()[0] == 0:
            sample_rewards = [
                ("น้ำดื่มตราช้าง 350ml แพ็ค 24 ขวด", 150, 999, "มูลค่า 120 บาท", 1, "https://images.unsplash.com/photo-1606857521015-7f9fcf423740?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80"),
                ("พวงมาลัยดอกมะลิพรีเมียม ขนาดใหญ่", 400, 50, "มูลค่า 350 บาท", 1, "https://images.unsplash.com/photo-1622484212850-eb596d0f9512?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80"),
            ]
            c.executemany("""
                INSERT INTO rewards (name, points_required, stock, description, is_active, image_url)
                VALUES (?, ?, ?, ?, ?, ?)
            """, sample_rewards)
            conn.commit()
        # ออเดอร์
        c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            status TEXT DEFAULT 'pending',
            total INTEGER DEFAULT 0,
            updated_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """)

        # order_items
        c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_name TEXT NOT NULL,
            price INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id)
        )
        """)

        conn.commit()

        # สร้าง admin ถ้ายังไม่มี
        c.execute("SELECT 1 FROM users WHERE username = 'admin'")
        if not c.fetchone():
            admin_hash = hash_password("admin123")  # เปลี่ยนรหัสผ่านจริง ๆ
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO users (username, email, password_hash, created_at, is_admin, phone) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("admin", "admin@example.com", admin_hash, now, 1, "0000000000")
            )
            admin_id = c.lastrowid
            conn.commit()

            # สร้าง user_points สำหรับ admin
            c.execute("""
                INSERT OR IGNORE INTO user_points 
                (user_id, available_points, earned_points, redeemed_points, pending_points, last_updated)
                VALUES (?, 0, 0, 0, 0, ?)
            """, (admin_id, now))
            conn.commit()

        # สินค้าตัวอย่าง
        c.execute("SELECT COUNT(*) FROM products")
        if c.fetchone()[0] == 0:
            sample_products = [
                ("พวงมาลัยดอกมะลิขนาดกลาง", 120, "พวงมาลัย"),
                ("พวงมาลัยดาวเรืองพลาสติก", 45, "พวงมาลัย"),
                ("น้ำดื่มตราช้าง 350ml แพ็ค 12 ขวด", 55, "น้ำ"),
                ("น้ำปัญจอมฤต 100ml", 180, "น้ำ"),
                ("ชุดธูปเทียนไหว้พระ 5 ชุด", 90, "อื่นๆ"),
                ("ผลไม้รวม (กล้วย ส้ม มะพร้าว)", 150, "อื่นๆ"),
            ]
            c.executemany("INSERT INTO products (name, price, category) VALUES (?, ?, ?)", sample_products)
            conn.commit()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

# ─── ระบบผู้ใช้ ────────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip()
        phone    = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not all([username, email, phone, password]):
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง", "danger")
            return redirect(url_for("register"))

        if password != password2:
            flash("รหัสผ่านไม่ตรงกัน", "danger")
            return redirect(url_for("register"))

        if not phone.isdigit() or not (9 <= len(phone) <= 10):
            flash("เบอร์โทรศัพท์ไม่ถูกต้อง (9-10 หลัก)", "danger")
            return redirect(url_for("register"))

        with get_db() as conn:
            c = conn.cursor()
            existing = c.execute(
                "SELECT 1 FROM users WHERE username = ? OR email = ? OR phone = ?",
                (username, email, phone)
            ).fetchone()

            if existing:
                flash("ข้อมูลนี้ถูกใช้งานแล้ว", "danger")
                return redirect(url_for("register"))

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pw_hash = hash_password(password)

            c.execute(
                "INSERT INTO users (username, email, phone, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (username, email, phone, pw_hash, now)
            )
            user_id = c.lastrowid
            conn.commit()

            # สร้าง user_points
            c.execute("""
                INSERT OR IGNORE INTO user_points 
                (user_id, available_points, earned_points, redeemed_points, pending_points, last_updated)
                VALUES (?, 0, 0, 0, 0, ?)
            """, (user_id, now))
            conn.commit()

            flash("สมัครสมาชิกสำเร็จ กรุณาเข้าสู่ระบบ", "success")
            return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_db() as conn:
            user = conn.execute(
                "SELECT id, username, password_hash, is_admin, phone FROM users WHERE username = ?",
                (username,)
            ).fetchone()

            if user and user["password_hash"] == hash_password(password):
                session["user_id"]   = user["id"]
                session["username"]  = user["username"]
                session["is_admin"]  = bool(user["is_admin"])
                session["phone"]     = user["phone"]   # ← เพิ่มบรรทัดนี้
                flash("เข้าสู่ระบบสำเร็จ", "success")
                return redirect(url_for("index"))
            else:
                flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    flash("ออกจากระบบแล้ว", "success")
    return redirect(url_for("index"))





# กำหนดโฟลเดอร์สำหรับเก็บรูปโปรไฟล์
UPLOAD_FOLDER = os.path.join('static', 'uploads', 'profiles')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# สร้างโฟลเดอร์ถ้ายังไม่มี
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        flash("กรุณาเข้าสู่ระบบก่อน", "danger")
        return redirect(url_for("login"))

    with get_db() as conn:
        if request.method == "POST":
            new_username = request.form.get("username", "").strip()
            new_email    = request.form.get("email", "").strip()
            new_phone    = request.form.get("phone", "").strip()
            new_password = request.form.get("new_password", "")

            # จัดการอัปโหลดรูปโปรไฟล์
            profile_pic = request.files.get("profile_picture")
            profile_pic_path = None

            if profile_pic and profile_pic.filename != '':
                if allowed_file(profile_pic.filename):
                    filename = secure_filename(f"{session['user_id']}_{profile_pic.filename}")
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    profile_pic.save(file_path)
                    profile_pic_path = f"uploads/profiles/{filename}"
                else:
                    flash("ไฟล์รูปไม่รองรับ (รองรับ .jpg, .jpeg, .png เท่านั้น)", "danger")
                    return redirect(url_for("profile"))

            # ดึงข้อมูลผู้ใช้ปัจจุบัน
            user = conn.execute(
                "SELECT username, email, phone, profile_picture FROM users WHERE id = ?",
                (session["user_id"],)
            ).fetchone()

            updates, params = [], []

            if new_username and new_username != user["username"]:
                updates.append("username = ?")
                params.append(new_username)

            if new_email and new_email != user["email"]:
                updates.append("email = ?")
                params.append(new_email)

            if new_phone and new_phone != user["phone"]:
                updates.append("phone = ?")
                params.append(new_phone)

            if profile_pic_path:
                updates.append("profile_picture = ?")
                params.append(profile_pic_path)

            if new_password:
                updates.append("password_hash = ?")
                params.append(hash_password(new_password))

            if updates:
                params.append(session["user_id"])
                query = "UPDATE users SET " + ", ".join(updates) + " WHERE id = ?"
                try:
                    conn.execute(query, params)
                    conn.commit()
                    flash("อัปเดตโปรไฟล์สำเร็จ", "success")

                    # อัปเดต session ถ้ามีการเปลี่ยน
                    if new_username:
                        session["username"] = new_username
                    if new_phone:
                        session["phone"] = new_phone

                except sqlite3.IntegrityError:
                    flash("ชื่อผู้ใช้, อีเมล หรือเบอร์โทรนี้ถูกใช้งานแล้ว", "danger")

        # ดึงข้อมูลล่าสุด
        user = conn.execute(
            "SELECT username, email, phone, created_at, profile_picture FROM users WHERE id = ?",
            (session["user_id"],)
        ).fetchone()

    return render_template("profile.html", user=user)

# ─── ระบบหลัก ──────────────────────────────────────────────────

@app.route("/")
def index():
    with get_db() as conn:
        products = conn.execute("SELECT * FROM products ORDER BY category, name").fetchall()

    success = request.args.get("success")

    return render_template(
        "index.html",
        products=products,
        success=success,
        current_year=datetime.now().year
    )


@app.route("/order", methods=["POST"])
def order():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    product_ids = request.form.getlist("product_id")

    if not name or not phone or not product_ids:
        return "ข้อมูลไม่ครบถ้วน", 400

    user_id = session.get("user_id")  # บันทึกว่าใครเป็นคนสั่ง (ถ้าล็อกอิน)

    with get_db() as conn:
        c = conn.cursor()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        c.execute(
            "INSERT INTO orders (customer_name, phone, created_at, user_id) VALUES (?, ?, ?, ?)",
            (name, phone, now, user_id)
        )
        order_id = c.lastrowid

        for pid in product_ids:
            qty_str = request.form.get(f"qty_{pid}", "0")
            try:
                qty = int(qty_str)
            except ValueError:
                qty = 0

            if qty > 0:
                product = conn.execute(
                    "SELECT name, price FROM products WHERE id = ?",
                    (pid,)
                ).fetchone()

                if product:
                    c.execute(
                        "INSERT INTO order_items (order_id, product_name, price, quantity) VALUES (?, ?, ?, ?)",
                        (order_id, product["name"], product["price"], qty)
                    )

        conn.commit()

    return redirect("/?success=1")


# ─── Admin ─────────────────────────────────────────────────────

# ─── Admin ─────────────────────────────────────────────────────

@app.route("/admin")
def admin():
    if not session.get("is_admin"):
        return redirect(url_for("index"))

    with get_db() as conn:
        rows = conn.execute("""
            SELECT o.id, o.customer_name, o.phone, o.created_at, o.status, o.total,
                oi.product_name AS product, oi.price, oi.quantity AS qty,
                u.profile_picture
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            LEFT JOIN users u ON o.user_id = u.id
            ORDER BY o.created_at DESC
        """).fetchall()

    grouped = {}
    for r in rows:
        oid = r['id']
        if oid not in grouped:
            grouped[oid] = {
                'id': oid, 'customer_name': r['customer_name'], 'phone': r['phone'],
                'created_at': r['created_at'], 'status': r['status'] or 'pending',
                'items': [], 'total': 0
            }
        if r['product']:
            sub = r['price'] * r['qty']
            grouped[oid]['items'].append({'product': r['product'], 'price': r['price'], 'qty': r['qty'], 'subtotal': sub})
            grouped[oid]['total'] += sub
            grouped[oid]['profile_picture'] = r['profile_picture']

    # แยกตามสถานะ
    pending_orders   = {k:v for k,v in grouped.items() if v['status'] == 'pending'}
    confirmed_orders = {k:v for k,v in grouped.items() if v['status'] == 'confirmed'}
    preparing_orders = {k:v for k,v in grouped.items() if v['status'] == 'preparing'}
    completed_orders = {k:v for k,v in grouped.items() if v['status'] == 'completed'}

    counts = {
        'pending_count': len(pending_orders),
        'confirmed_count': len(confirmed_orders),
        'preparing_count': len(preparing_orders),
        'completed_count': len(completed_orders),
        'total_revenue': sum(o['total'] for o in grouped.values())
    }

    return render_template(
        "admin.html",
        pending_orders=pending_orders,
        confirmed_orders=confirmed_orders,
        preparing_orders=preparing_orders,
        completed_orders=completed_orders,
        **counts
    )
    
from flask import flash, redirect, url_for, request, session
from datetime import datetime

@app.route("/admin/update-order-status/<int:order_id>", methods=["POST"])
def update_order_status(order_id):
    if not session.get("is_admin"):
        flash("คุณไม่มีสิทธิ์", "danger")
        return redirect(url_for("admin"))

    next_status = request.form.get("next_status")
    valid_transitions = {
        'pending': ['confirmed'],
        'confirmed': ['preparing'],
        'preparing': ['completed'],
        'completed': []
    }

    with get_db() as conn:
        current = conn.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not current:
            flash(f"ไม่พบออเดอร์ #{order_id}", "danger")
            return redirect(url_for("admin"))

        current_status = current['status'] or 'pending'

        if next_status not in valid_transitions.get(current_status, []):
            flash(f"ไม่สามารถเปลี่ยนสถานะจาก '{current_status}' เป็น '{next_status}'", "warning")
            return redirect(url_for("admin"))

        if next_status == 'completed':
            total = conn.execute(
                "SELECT SUM(price * quantity) FROM order_items WHERE order_id = ?",
                (order_id,)
            ).fetchone()[0] or 0

            points_earned = total // 10

            # Debug print
            print(f"[DEBUG] Order #{order_id} completed | Total: {total} บาท | Earn {points_earned} points")

            user_row = conn.execute(
                "SELECT user_id FROM orders WHERE id = ?",
                (order_id,)
            ).fetchone()

            if user_row and user_row['user_id']:
                print(f"[DEBUG] Updating points for user_id: {user_row['user_id']}")
                conn.execute("""
                    UPDATE user_points 
                    SET 
                        available_points = available_points + ?,
                        earned_points = earned_points + ?,
                        last_updated = ?
                    WHERE user_id = ?
                """, (points_earned, points_earned, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_row['user_id']))
            else:
                print("[DEBUG] No user_id found → points NOT added")

        try:
            conn.execute(
                "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                (next_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), order_id)
            )
            conn.commit()

            status_display = {
                'confirmed': 'ยืนยันแล้ว',
                'preparing': 'กำลังจัดของ',
                'completed': 'ปิดจ๊อบ / เสร็จสิ้น'
            }.get(next_status, next_status)

            flash(f"อัปเดตสถานะออเดอร์ #{order_id} เป็น '{status_display}' สำเร็จ", "success")
        except Exception as e:
            conn.rollback()
            flash(f"เกิดข้อผิดพลาด: {str(e)}", "danger")

    return redirect(url_for("admin"))

@app.route("/admin/products")
def admin_products():
    with get_db() as conn:
        products = conn.execute("SELECT * FROM products ORDER BY id").fetchall()

    success = request.args.get("success")
    error = request.args.get("error")

    return render_template("admin_products.html", 
                           products=products,
                           success=success,
                           error=error)


@app.route("/admin/product/add", methods=["POST"])
def add_product():
    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()

    if not name or not price.isdigit():
        return redirect("/admin/products?error=ข้อมูลไม่ครบหรือราคาไม่ถูกต้อง")

    price = int(price)
    if price < 0:
        return redirect("/admin/products?error=ราคาต้องไม่ติดลบ")

    with get_db() as conn:
        conn.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
        conn.commit()

    return redirect("/admin/products?success=เพิ่มสินค้าแล้ว")


from flask import flash, url_for

@app.route("/admin/product/edit/<int:pid>", methods=["GET", "POST"])
def edit_product(pid):
    with get_db() as conn:
        if request.method == "GET":
            product = conn.execute(
                "SELECT id, name, price, category FROM products WHERE id = ?",
                (pid,)
            ).fetchone()
            
            if not product:
                flash("ไม่พบสินค้าที่ต้องการแก้ไข", "danger")
                return redirect(url_for("admin_products"))
            
            return render_template("edit_product.html", product=product)

        # POST - แก้ไขข้อมูล
        name     = request.form.get("name", "").strip()
        price    = request.form.get("price", "").strip()
        category = request.form.get("category", "อื่นๆ").strip()

        # ตรวจสอบข้อมูลที่จำเป็น
        errors = []
        if not name:
            errors.append("กรุณากรอกชื่อสินค้า")
        if not price or not price.isdigit():
            errors.append("ราคาต้องเป็นตัวเลขเท่านั้น")
        else:
            price_int = int(price)
            if price_int < 0:
                errors.append("ราคาไม่สามารถติดลบได้")

        # ตรวจสอบหมวดหมู่ (optional: ถ้าต้องการจำกัดเฉพาะหมวดที่กำหนด)
        valid_categories = ["พวงมาลัย", "ของไหว้", "น้ำ", "อื่นๆ"]
        if category not in valid_categories:
            category = "อื่นๆ"  # fallback ถ้าค่าผิดปกติ

        if errors:
            error_msg = " | ".join(errors)
            flash(error_msg, "danger")
            return redirect(url_for("edit_product", pid=pid))

        # อัปเดตข้อมูล
        try:
            conn.execute(
                "UPDATE products SET name = ?, price = ?, category = ? WHERE id = ?",
                (name, price_int, category, pid)
            )
            conn.commit()
            flash("แก้ไขสินค้าเรียบร้อยแล้ว", "success")
        except Exception as e:
            flash(f"เกิดข้อผิดพลาดในการบันทึก: {str(e)}", "danger")
            return redirect(url_for("edit_product", pid=pid))

    return redirect(url_for("admin_products"))


@app.route("/admin/product/delete/<int:pid>", methods=["POST"])
def delete_product(pid):
    with get_db() as conn:
        used = conn.execute("""
            SELECT 1 FROM order_items 
            WHERE product_name = (SELECT name FROM products WHERE id = ?)
            LIMIT 1
        """, (pid,)).fetchone()

        if used:
            return redirect("/admin/products?error=ไม่สามารถลบได้ เพราะมีออเดอร์ที่ใช้สินค้านี้แล้ว")

        conn.execute("DELETE FROM products WHERE id = ?", (pid,))
        conn.commit()

    return redirect("/admin/products?success=ลบสินค้าแล้ว")

def dateformat(value, format='%d %b %Y %H:%M น.'):
    if value is None:
        return ""
    try:
        dt = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        return dt.strftime(format)
    except:
        return value  # ถ้าแปลงไม่ได้ ให้คืนค่าเดิม

app.jinja_env.filters['dateformat'] = dateformat


@app.route("/my-orders")
def my_orders():
    # ต้องล็อกอินก่อนเท่านั้น
    if "user_id" not in session:
        flash("กรุณาเข้าสู่ระบบก่อนดูประวัติการสั่งซื้อ", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with get_db() as conn:
        # ดึงข้อมูลออเดอร์ของผู้ใช้คนนี้เท่านั้น
        rows = conn.execute("""
            SELECT 
                orders.id,
                orders.customer_name,
                orders.phone,
                orders.created_at,
                orders.status,
                order_items.product_name,
                order_items.price,
                order_items.quantity
            FROM orders
            LEFT JOIN order_items ON orders.id = order_items.order_id
            WHERE orders.user_id = ?
            ORDER BY orders.created_at DESC
        """, (user_id,)).fetchall()

    # จัดกลุ่มข้อมูลตาม order_id
    grouped = {}
    for r in rows:
        oid = r["id"]
        if oid not in grouped:
            grouped[oid] = {
                "id": oid,
                "customer_name": r["customer_name"],
                "phone": r["phone"],
                "created_at": r["created_at"],
                "status": r["status"] or "pending",
                "items": [],
                "total": 0
            }

        if r["product_name"]:  # มีรายการสินค้า
            subtotal = r["price"] * r["quantity"]
            grouped[oid]["items"].append({
                "product": r["product_name"],
                "price": r["price"],
                "qty": r["quantity"],
                "subtotal": subtotal
            })
            grouped[oid]["total"] += subtotal

    return render_template(
        "my_orders.html",
        orders=grouped,
        user_name=session.get("username", "ผู้ใช้")
    )

@app.route("/privacy")
def privacy():
    return render_template("privacy.html")

@app.route("/terms")
def terms():
    return render_template("terms.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():

    if request.method == "POST":

        name = request.form.get("name")
        email = request.form.get("email")
        message = request.form.get("message")

        print("Contact message:")
        print(name, email, message)

        return render_template("contact.html", success=True)

    return render_template("contact.html")

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        flash("กรุณาเข้าสู่ระบบก่อน", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]

    with get_db() as conn:
        # 1. ยอดสัปดาห์นี้ (7 วันล่าสุด)
        weekly_total = conn.execute("""
            SELECT COALESCE(SUM(oi.price * oi.quantity), 0)
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            WHERE o.user_id = ?
            AND o.created_at >= date('now', '-7 days')
            AND o.status = 'completed'
        """, (user_id,)).fetchone()[0]

        # 2. ยอดเดือนนี้
        monthly_total = conn.execute("""
            SELECT COALESCE(SUM(oi.price * oi.quantity), 0)
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            WHERE o.user_id = ?
            AND strftime('%Y-%m', o.created_at) = strftime('%Y-%m', 'now')
            AND o.status = 'completed'
        """, (user_id,)).fetchone()[0]

        # 3. ยอดปีนี้ (เพิ่มบรรทัดนี้!)
        yearly_total = conn.execute("""
            SELECT COALESCE(SUM(oi.price * oi.quantity), 0)
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            WHERE o.user_id = ?
            AND strftime('%Y', o.created_at) = strftime('%Y', 'now')
            AND o.status = 'completed'
        """, (user_id,)).fetchone()[0]

        # 4. ยอดทั้งหมด
        all_time_total = conn.execute("""
            SELECT COALESCE(SUM(oi.price * oi.quantity), 0)
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            WHERE o.user_id = ? AND o.status = 'completed'
        """, (user_id,)).fetchone()[0]

        # 5. ข้อมูลกราฟรายเดือน (6 เดือนล่าสุด)
        monthly_rows = conn.execute("""
            SELECT strftime('%Y-%m', o.created_at) AS month,
                   COALESCE(SUM(oi.price * oi.quantity), 0) AS total
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            WHERE o.user_id = ?
            AND o.created_at >= date('now', '-6 months')
            AND o.status = 'completed'
            GROUP BY month
            ORDER BY month ASC
        """, (user_id,)).fetchall()

        monthly_labels = []
        monthly_data = []
        for row in monthly_rows:
            y, m = row['month'].split('-')
            month_name = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 
                          'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'][int(m)-1]
            monthly_labels.append(f"{month_name} {y}")
            monthly_data.append(int(row['total']))

        # 6. แต้ม (ใช้ fallback ถ้าตารางไม่มี)
        try:
            points = conn.execute("""
                SELECT available_points, earned_points, redeemed_points, pending_points
                FROM user_points WHERE user_id = ?
            """, (user_id,)).fetchone()
            if points:
                available_points, earned_points, redeemed_points, pending_points = points
            else:
                available_points = earned_points = redeemed_points = pending_points = 0
        except sqlite3.OperationalError:
            available_points = earned_points = redeemed_points = pending_points = 0

    return render_template(
        "dashboard.html",
        weekly_total=weekly_total,
        monthly_total=monthly_total,
        yearly_total=yearly_total,          # ← เพิ่มบรรทัดนี้!
        all_time_total=all_time_total,
        monthly_labels=monthly_labels,
        monthly_data=monthly_data,
        available_points=available_points,
        earned_points=earned_points,
        redeemed_points=redeemed_points,
        pending_points=pending_points,
        current_time=datetime.now().strftime("%d %b %Y %H:%M น.")
    )

@app.route("/rewards")
def rewards():
    if "user_id" not in session:
        flash("กรุณาเข้าสู่ระบบก่อน", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    with get_db() as conn:
        points = conn.execute("SELECT * FROM user_points WHERE user_id = ?", (user_id,)).fetchone()
        available_points = points['available_points'] if points else 0
        earned_points = points['earned_points'] if points else 0
        redeemed_points = points['redeemed_points'] if points else 0
        pending_points = points['pending_points'] if points else 0

        # ดึงรางวัลจากฐานข้อมูลแทน hard-code
        rewards = conn.execute("""
            SELECT id, name, points_required, description, image_url 
            FROM rewards 
            WHERE is_active = 1 
            ORDER BY points_required ASC
        """).fetchall()

        history = conn.execute("""
            SELECT reward_name, points_used, redeemed_at 
            FROM redeemed_rewards 
            WHERE user_id = ? 
            ORDER BY redeemed_at DESC 
            LIMIT 10
        """, (user_id,)).fetchall()

    return render_template(
        "rewards.html",
        available_points=available_points,
        earned_points=earned_points,
        redeemed_points=redeemed_points,
        pending_points=pending_points,
        rewards=rewards,               # ← ใหม่
        redeemed_history=history,
        current_time=datetime.now().strftime("%d %b %Y %H:%M น.")
    )


@app.route("/redeem", methods=["POST"])
def redeem():
    if "user_id" not in session:
        flash("กรุณาเข้าสู่ระบบก่อน", "danger")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    reward_id = request.form.get("reward_id")

    if not reward_id:
        flash("ไม่พบรางวัลที่เลือก", "danger")
        return redirect(url_for("rewards"))

    with get_db() as conn:
        # ดึงข้อมูลรางวัลจากฐานข้อมูล
        reward = conn.execute("""
            SELECT name, points_required, stock 
            FROM rewards 
            WHERE id = ? AND is_active = 1
        """, (reward_id,)).fetchone()

        if not reward:
            flash("รางวัลนี้ไม่ถูกต้องหรือถูกปิดใช้งาน", "danger")
            return redirect(url_for("rewards"))

        reward_name = reward['name']
        points_needed = reward['points_required']
        stock = reward['stock']

        if stock <= 0:
            flash(f"รางวัล '{reward_name}' หมดสต็อกแล้ว", "warning")
            return redirect(url_for("rewards"))

        # ตรวจแต้ม
        points_row = conn.execute("SELECT available_points FROM user_points WHERE user_id = ?", (user_id,)).fetchone()
        if not points_row or points_row['available_points'] < points_needed:
            flash(f"แต้มไม่พอ ต้องใช้ {points_needed} แต้ม (คุณมี {points_row['available_points'] or 0})", "danger")
            return redirect(url_for("rewards"))

        # หักแต้ม
        conn.execute("""
            UPDATE user_points 
            SET 
                available_points = available_points - ?,
                redeemed_points = redeemed_points + ?,
                last_updated = datetime('now')
            WHERE user_id = ?
        """, (points_needed, points_needed, user_id))

        # หักสต็อก (optional แต่ควรมี)
        conn.execute("UPDATE rewards SET stock = stock - 1 WHERE id = ?", (reward_id,))

        # บันทึกประวัติ
        conn.execute("""
            INSERT INTO redeemed_rewards (user_id, reward_name, points_used, redeemed_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (user_id, reward_name, points_needed))

        conn.commit()

    flash(f"แลกรางวัล '{reward_name}' สำเร็จ! ขอบคุณมากครับ", "success")
    return redirect(url_for("rewards"))

@app.template_filter('format_number')
def format_number(value):
    return "{:,}".format(int(value))

from flask import jsonify

@app.route("/admin/orders/latest", methods=["GET"])
def admin_latest_orders():
    if not session.get("is_admin"):
        return jsonify({"error": "Unauthorized"}), 403

    with get_db() as conn:
        rows = conn.execute("""
            SELECT o.id, o.customer_name, o.phone, o.created_at, o.status, o.total,
                   oi.product_name AS product, oi.price, oi.quantity AS qty,
                   u.profile_picture
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            LEFT JOIN users u ON o.user_id = u.id
            ORDER BY o.created_at DESC
        """).fetchall()

        grouped = {}
        for r in rows:
            oid = r['id']
            if oid not in grouped:
                grouped[oid] = {
                    'id': oid,
                    'customer_name': r['customer_name'],
                    'phone': r['phone'],
                    'created_at': r['created_at'],
                    'status': r['status'] or 'pending',
                    'total': r['total'] or 0,
                    'profile_picture': r['profile_picture'],
                    'items': []
                }
            if r['product']:
                sub = r['price'] * r['qty']
                grouped[oid]['items'].append({
                    'product': r['product'],
                    'price': r['price'],
                    'qty': r['qty'],
                    'subtotal': sub
                })
                grouped[oid]['total'] += sub

        pending_orders   = {k: v for k, v in grouped.items() if v['status'] == 'pending'}
        confirmed_orders = {k: v for k, v in grouped.items() if v['status'] == 'confirmed'}
        preparing_orders = {k: v for k, v in grouped.items() if v['status'] == 'preparing'}
        completed_orders = {k: v for k, v in grouped.items() if v['status'] == 'completed'}

        counts = {
            'pending_count': len(pending_orders),
            'confirmed_count': len(confirmed_orders),
            'preparing_count': len(preparing_orders),
            'completed_count': len(completed_orders)
        }

        return jsonify({
            'counts': counts,
            'last_updated': datetime.now().strftime("%d %b %Y %H:%M น.")
        })
        
@app.route("/admin/orders/pending-update")
def admin_pending_update():
    if not session.get("is_admin"):
        return "Unauthorized", 403

    with get_db() as conn:
        # ดึงข้อมูล orders แบบเดิม (เฉพาะ pending)
        rows = conn.execute("""
            SELECT o.id, o.customer_name, o.phone, o.created_at, o.status, o.total,
                   oi.product_name AS product, oi.price, oi.quantity AS qty,
                   u.profile_picture
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            LEFT JOIN users u ON o.user_id = u.id
            WHERE o.status = 'pending'
            ORDER BY o.created_at DESC
        """).fetchall()

        grouped = {}
        for r in rows:
            oid = r['id']
            if oid not in grouped:
                grouped[oid] = {
                    'id': oid,
                    'customer_name': r['customer_name'],
                    'phone': r['phone'],
                    'created_at': r['created_at'],
                    'status': r['status'] or 'pending',
                    'total': r['total'] or 0,
                    'profile_picture': r['profile_picture'],
                    'items': []
                }
            if r['product']:
                sub = r['price'] * r['qty']
                grouped[oid]['items'].append({
                    'product': r['product'],
                    'price': r['price'],
                    'qty': r['qty'],
                    'subtotal': sub
                })
                grouped[oid]['total'] += sub

        pending_count = len(grouped)

        pending_html = render_template(
            "admin_pending_partial.html",
            pending_orders=grouped,
            pending_count=pending_count
        )

        return jsonify({
            'pending_count': pending_count,
            'pending_html': pending_html
        })


@app.route("/admin/orders/pending-partial")
def admin_pending_partial():
    if not session.get("is_admin"):
        return "Unauthorized", 403

    with get_db() as conn:
        rows = conn.execute("""
            SELECT o.id, o.customer_name, o.phone, o.created_at, o.status, o.total,
                   oi.product_name AS product, oi.price, oi.quantity AS qty,
                   u.profile_picture
            FROM orders o
            LEFT JOIN order_items oi ON o.id = oi.order_id
            LEFT JOIN users u ON o.user_id = u.id
            WHERE o.status = 'pending'
            ORDER BY o.created_at DESC
        """).fetchall()

        grouped = {}
        for r in rows:
            oid = r['id']
            if oid not in grouped:
                grouped[oid] = {
                    'id': oid,
                    'customer_name': r['customer_name'],
                    'phone': r['phone'],
                    'created_at': r['created_at'],
                    'status': r['status'],
                    'total': r['total'] or 0,
                    'profile_picture': r['profile_picture'],
                    'items': []
                }
            if r['product']:
                sub = r['price'] * r['qty']
                grouped[oid]['items'].append({
                    'product': r['product'],
                    'price': r['price'],
                    'qty': r['qty'],
                    'subtotal': sub
                })
                grouped[oid]['total'] += sub

        return render_template(
            "admin_pending_partial.html",
            pending_orders=grouped
        )
        
@app.route("/admin/order/<int:order_id>")
def admin_view_order(order_id):
    if not session.get("is_admin"):
        flash("คุณไม่มีสิทธิ์", "danger")
        return redirect(url_for("admin"))

    with get_db() as conn:
        order = conn.execute("""
            SELECT o.*, u.profile_picture
            FROM orders o
            LEFT JOIN users u ON o.user_id = u.id
            WHERE o.id = ?
        """, (order_id,)).fetchone()

        if not order:
            flash(f"ไม่พบออเดอร์ #{order_id}", "danger")
            return redirect(url_for("admin"))

        items = conn.execute("""
            SELECT product_name, price, quantity
            FROM order_items
            WHERE order_id = ?
        """, (order_id,)).fetchall()

        return render_template(
            "admin_view_order.html",
            order=order,
            items=items
        )
# ─── Start ─────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()           # สร้างตารางถ้ายังไม่มี
    app.run(
        host="0.0.0.0",
        port=6450,
        debug=True      # เปลี่ยนเป็น False เมื่อใช้งานจริง
    )