from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import datetime
import os

app = Flask(__name__)

# ใช้ absolute path เพื่อป้องกันปัญหา path ไม่ตรง
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "database.db")


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # สร้างตารางถ้ายังไม่มี (ไม่เพิ่มสินค้าอัตโนมัติอีกต่อไป)
    c.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        price INTEGER NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        price INTEGER NOT NULL,
        quantity INTEGER NOT NULL
    )
    """)

    conn.commit()
    conn.close()


@app.route("/")
def index():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    conn.close()

    success = request.args.get("success")

    return render_template(
        "index.html",
        products=products,
        success=success,
        current_year=datetime.now().year   # เพิ่มบรรทัดนี้
    )


@app.route("/order", methods=["POST"])
def order():
    name = request.form.get("name")
    phone = request.form.get("phone")
    product_ids = request.form.getlist("product_id")

    if not name or not phone or not product_ids:
        return "ข้อมูลไม่ครบ", 400

    conn = get_db()
    c = conn.cursor()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute(
        "INSERT INTO orders (customer_name, phone, created_at) VALUES (?, ?, ?)",
        (name, phone, now)
    )

    order_id = c.lastrowid

    for pid in product_ids:
        qty_str = request.form.get(f"qty_{pid}", "0")
        try:
            qty = int(qty_str)
        except ValueError:
            qty = 0

        if qty <= 0:
            continue  # ข้ามถ้าไม่ได้เลือกจริง ๆ

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
    conn.close()

    return redirect("/?success=1")


@app.route("/admin")
def admin():
    conn = get_db()

    rows = conn.execute("""
        SELECT 
            orders.id,
            orders.customer_name,
            orders.phone,
            orders.created_at,
            order_items.product_name,
            order_items.price,
            order_items.quantity
        FROM orders
        JOIN order_items ON orders.id = order_items.order_id
        ORDER BY orders.id DESC
    """).fetchall()

    conn.close()
    
    grouped_orders = {}

    for row in rows:
        order_id = row["id"]
        if order_id not in grouped_orders:
            grouped_orders[order_id] = {
                "customer_name": row["customer_name"],
                "phone": row["phone"],
                "created_at": row["created_at"],
                "items": [],
                "total": 0
            }

        subtotal = row["price"] * row["quantity"]

        grouped_orders[order_id]["items"].append({
            "product": row["product_name"],
            "price": row["price"],
            "qty": row["quantity"],
            "subtotal": subtotal
        })

        grouped_orders[order_id]["total"] += subtotal

    total_orders = len(grouped_orders)
    total_revenue = sum(order["total"] for order in grouped_orders.values())

    return render_template(
        "admin.html",
        orders=grouped_orders,
        total_orders=total_orders,
        total_revenue=total_revenue
    )


@app.route("/admin/products")
def admin_products():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    conn.close()
    
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
    
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO products (name, price) VALUES (?, ?)", (name, price))
    conn.commit()
    conn.close()
    
    return redirect("/admin/products?success=เพิ่มสินค้าแล้ว")


@app.route("/admin/product/edit/<int:pid>", methods=["GET", "POST"])
def edit_product(pid):
    conn = get_db()
    
    if request.method == "GET":
        product = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
        conn.close()
        
        if not product:
            return redirect("/admin/products?error=ไม่พบสินค้า")
            
        return render_template("edit_product.html", product=product)
    
    # POST = อัพเดท
    name = request.form.get("name", "").strip()
    price = request.form.get("price", "").strip()
    
    if not name or not price.isdigit():
        return redirect(f"/admin/product/edit/{pid}?error=ข้อมูลไม่ครบหรือราคาไม่ถูกต้อง")
    
    price = int(price)
    if price < 0:
        return redirect(f"/admin/product/edit/{pid}?error=ราคาต้องไม่ติดลบ")
    
    conn = get_db()
    conn.execute("UPDATE products SET name = ?, price = ? WHERE id = ?", (name, price, pid))
    conn.commit()
    conn.close()
    
    return redirect("/admin/products?success=แก้ไขสินค้าแล้ว")


@app.route("/admin/product/delete/<int:pid>", methods=["POST"])
def delete_product(pid):
    conn = get_db()
    
    used = conn.execute("""
        SELECT 1 FROM order_items 
        WHERE product_name = (SELECT name FROM products WHERE id = ?)
        LIMIT 1
    """, (pid,)).fetchone()
    
    if used:
        conn.close()
        return redirect("/admin/products?error=ไม่สามารถลบได้ เพราะมีออเดอร์ที่ใช้สินค้านี้แล้ว")
    
    conn.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()
    
    return redirect("/admin/products?success=ลบสินค้าแล้ว")


# เรียก init_db() ครั้งเดียวตอนเริ่มโปรแกรม (สร้างตารางถ้ายังไม่มี)
init_db()

if __name__ == "__main__":
    # init_db() เรียกอีกครั้งเพื่อความชัวร์ (แต่จะไม่เพิ่มสินค้าซ้ำเพราะ comment ส่วนนั้นออกแล้ว)
    init_db()
    app.run(
        host="0.0.0.0",
        port=6450,
        debug=True   # เปิด debug ชั่วคราวเพื่อดู error ชัดเจน ถ้าทำงานปกติแล้วเปลี่ยนเป็น False ได้
    )