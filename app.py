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

app = Flask(__name__)

# ─── การตั้งค่าที่สำคัญมาก (เรียงลำดับแบบนี้ดีที่สุด) ────────────────────────────────
app.secret_key = os.environ.get("SECRET_KEY") or "super-secret-key-change-this-2025-geotran-manss-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# ป้องกันปัญหา CSRF token หาย / ไม่ sync ในบาง browser
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False          # เปลี่ยนเป็น True เมื่อใช้ HTTPS จริง
app.config['PERMANENT_SESSION_LIFETIME'] = 86400     # 1 วัน (หน่วยเป็นวินาที)

# เปิด CSRF protection
csrf = CSRFProtect(app)
@app.context_processor
def inject_csrf():
    return dict(csrf_token=generate_csrf)
# ถ้าอยาก debug CSRF ได้ง่ายขึ้น (ลบออกตอน production)
# app.config['WTF_CSRF_CHECK_DEFAULT'] = True
# app.config['WTF_CSRF_TIME_LIMIT'] = 3600          # 1 ชั่วโมง

# Path ฐานข้อมูล (ส่วนที่เหลือเหมือนเดิม)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "database.db")


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        c = conn.cursor()

        # ตารางสินค้า
        # ตารางสินค้า (เพิ่ม category ถ้ายังไม่มี)
        c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            category TEXT DEFAULT 'อื่นๆ'  -- หมวดหมู่เริ่มต้น
        )
        """)

        # ถ้าตารางมีอยู่แล้วแต่ยังไม่มีคอลัมน์ category → เพิ่มเข้าไป
        try:
            c.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'อื่นๆ'")
        except sqlite3.OperationalError:
            pass  # มีคอลัมน์นี้อยู่แล้ว

        # ตารางผู้ใช้
        c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0   -- 0 = user, 1 = admin
        )
        """)
        # เพิ่มคอลัมน์ phone ถ้ายังไม่มี
        try:
            c.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        except sqlite3.OperationalError:
            pass  # ถ้ามีแล้ว ข้ามไป
        # ตารางออเดอร์
        c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
        """)
                # เพิ่ม status ใน orders ถ้ายังไม่มี
        try:
            c.execute("ALTER TABLE orders ADD COLUMN status TEXT DEFAULT 'pending'")
        except sqlite3.OperationalError:
            pass  # ถ้ามีคอลัมน์อยู่แล้ว ข้ามไป

        # รายการสินค้าในออเดอร์
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


        # (optional) สร้าง admin คนแรก ถ้ายังไม่มี (ทำครั้งเดียว)
        c.execute("SELECT 1 FROM users WHERE username = 'admin'")
        if not c.fetchone():
            admin_hash = hash_password("admin123")  # เปลี่ยนรหัสผ่านจริง ๆ นะ
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute(
                "INSERT INTO users (username, email, password_hash, created_at, is_admin) "
                "VALUES (?, ?, ?, ?, ?)",
                ("admin", "admin@example.com", admin_hash, now, 1)
            )
            conn.commit()
    # (optional) เพิ่มสินค้าตัวอย่างเริ่มต้น ถ้ายังไม่มีสินค้าเลย
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
    """Hash รหัสผ่านแบบง่าย (production ควรเปลี่ยนเป็น bcrypt)"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


# ─── ระบบผู้ใช้ ────────────────────────────────────────────────
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip()
        phone    = request.form.get("phone", "").strip()          # เพิ่มบรรทัดนี้
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")

        if not username or not email or not phone or not password:
            flash("กรุณากรอกข้อมูลให้ครบทุกช่อง (รวมเบอร์โทร)", "danger")
            return redirect(url_for("register"))

        if password != password2:
            flash("รหัสผ่านกับยืนยันรหัสผ่านไม่ตรงกัน", "danger")
            return redirect(url_for("register"))

        # ตรวจสอบความถูกต้องของเบอร์โทร (ตัวอย่างง่าย ๆ)
        if not phone.isdigit() or not (9 <= len(phone) <= 10):
            flash("เบอร์โทรศัพท์ไม่ถูกต้อง (ต้องเป็นตัวเลข 9-10 หลัก)", "danger")
            return redirect(url_for("register"))

        with get_db() as conn:
            c = conn.cursor()
            existing = c.execute(
                "SELECT 1 FROM users WHERE username = ? OR email = ? OR phone = ?",
                (username, email, phone)
            ).fetchone()

            if existing:
                flash("ชื่อผู้ใช้, อีเมล หรือเบอร์โทรนี้ถูกใช้งานแล้ว", "danger")
                return redirect(url_for("register"))

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            pw_hash = hash_password(password)

            try:
                c.execute(
                    "INSERT INTO users (username, email, phone, password_hash, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username, email, phone, pw_hash, now)
                )
                conn.commit()
                flash("สมัครสมาชิกสำเร็จ กรุณาเข้าสู่ระบบ", "success")
                return redirect(url_for("login"))
            except sqlite3.IntegrityError:
                flash("เกิดข้อผิดพลาด ข้อมูลซ้ำ (ชื่อผู้ใช้/อีเมล/เบอร์โทร)", "danger")

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


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        flash("กรุณาเข้าสู่ระบบก่อน", "danger")
        return redirect(url_for("login"))

    with get_db() as conn:
        if request.method == "POST":
            new_username = request.form.get("username", "").strip()
            new_email    = request.form.get("email", "").strip()
            new_phone    = request.form.get("phone", "").strip()          # เพิ่ม
            new_password = request.form.get("new_password", "")

            user = conn.execute(
                "SELECT username, email, phone FROM users WHERE id = ?",
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
                    if new_username:
                        session["username"] = new_username
                    if new_phone:                           # ← เพิ่มส่วนนี้
                        session["phone"] = new_phone
                except sqlite3.IntegrityError:
                    flash("ชื่อผู้ใช้, อีเมล หรือเบอร์โทรนี้ถูกใช้งานแล้ว", "danger")

        # ดึงข้อมูลล่าสุด (รวม phone)
        user = conn.execute(
            "SELECT username, email, phone, created_at FROM users WHERE id = ?",
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
        flash("คุณไม่มีสิทธิ์เข้าถึงหน้านี้", "danger")
        return redirect(url_for("index"))

    with get_db() as conn:
        rows = conn.execute("""
            SELECT 
                orders.id,
                orders.customer_name,
                orders.phone,
                orders.created_at,
                orders.user_id,
                orders.status,
                order_items.product_name,
                order_items.price,
                order_items.quantity
            FROM orders
            LEFT JOIN order_items ON orders.id = order_items.order_id
            ORDER BY orders.id DESC
        """).fetchall()

    grouped = {}
    for r in rows:
        oid = r["id"]
        
        # ตรวจสอบว่ามี oid นี้หรือยัง ถ้ายังไม่มีให้สร้าง dict ใหม่
        if oid not in grouped:
            grouped[oid] = {
                "id": oid,
                "customer_name": r["customer_name"],
                "phone": r["phone"],
                "created_at": r["created_at"],
                "user_id": r["user_id"],
                "status": r["status"] or "pending",
                "items": [],           # ← ต้องมีบรรทัดนี้! กำหนด list ว่างก่อน
                "total": 0
            }

        # ถ้ามีข้อมูลสินค้า (product_name ไม่ว่าง) ค่อย append
        if r["product_name"]:
            subtotal = r["price"] * r["quantity"]
            grouped[oid]["items"].append({      # ← ตรงนี้จะทำงานได้เพราะมี "items" แล้ว
                "product": r["product_name"],
                "price": r["price"],
                "qty": r["quantity"],
                "subtotal": subtotal
            })
            grouped[oid]["total"] += subtotal

    total_orders = len(grouped)
    total_revenue = sum(o["total"] for o in grouped.values())

    return render_template(
        "admin.html",
        orders=grouped,
        total_orders=total_orders,
        total_revenue=total_revenue
    )
    
# Route ยืนยันออเดอร์ (คุณมีอยู่แล้ว แต่เพิ่มการป้องกันเพิ่มเติม)
@app.route("/admin/confirm-order/<int:order_id>", methods=["POST"])
def confirm_order(order_id):
    if not session.get("is_admin"):
        flash("คุณไม่มีสิทธิ์ดำเนินการนี้", "danger")
        return redirect(url_for("index"))

    with get_db() as conn:
        order = conn.execute(
            "SELECT status FROM orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        if not order:
            flash("ไม่พบออเดอร์ที่ระบุ", "danger")
            return redirect(url_for("admin"))

        if order["status"] != "pending":
            flash("ออเดอร์นี้ถูกดำเนินการไปแล้วหรือสถานะไม่สามารถยืนยันได้", "warning")
            return redirect(url_for("admin"))

        conn.execute(
            "UPDATE orders SET status = 'confirmed' WHERE id = ?",
            (order_id,)
        )
        conn.commit()

    flash(f"ยืนยันรับออเดอร์ #{order_id} สำเร็จแล้ว", "success")
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

# ─── Start ─────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()           # สร้างตารางถ้ายังไม่มี
    app.run(
        host="0.0.0.0",
        port=6450,
        debug=True      # เปลี่ยนเป็น False เมื่อใช้งานจริง
    )