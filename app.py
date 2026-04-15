from flask import Flask, render_template, request, redirect, url_for, send_file, session, jsonify
from urllib.parse import quote_plus
from io import BytesIO
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from sqlalchemy import func
from models import db, MenuItem, Order, OrderItem, init_db, Customer, User
import qrcode
import os
import time
import socket
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'images')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def get_local_ip():
    """Get the local network IP address so phones on the same WiFi can connect"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        if local_ip and not local_ip.startswith('127.'):
            return local_ip
    except Exception:
        pass

    return '127.0.0.1'


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_public_url():
    """Get the public URL for the site.

    If PUBLIC_URL is configured, that URL will be used so the QR code is
    valid from any phone or any network. Otherwise, the app falls back to
    local network access for development.
    """
    # Force HTTPS if requested in environment
    force_https = os.getenv('FORCE_HTTPS', 'false').lower() in ['1', 'true', 'yes']

    public_url = os.getenv('PUBLIC_URL', '').strip().rstrip('/')
    if public_url:
        if force_https and public_url.startswith('http://'):
            public_url = 'https://' + public_url.split('://', 1)[1]
        elif not public_url.startswith(('http://', 'https://')):
            public_url = f"https://{public_url}"
        return public_url

    if request and hasattr(request, 'headers'):
        scheme = request.headers.get('X-Forwarded-Proto', request.scheme or 'http')
        host = request.headers.get('X-Forwarded-Host') or request.host

        if force_https or os.environ.get('FLASK_ENV') == 'production':
            scheme = 'https'

        if host.startswith('0.0.0.0'):
            host = host.replace('0.0.0.0', get_local_ip())

        if 'localhost' in host or '127.0.0.1' in host or host.startswith('0.0.0.0'):
            local_ip = get_local_ip()
            port = host.split(':')[-1] if ':' in host else '5000'
            return f'{scheme}://{local_ip}:{port}'

        return f'{scheme}://{host}'

    local_ip = get_local_ip()
    return f'https://{local_ip}:5000' if force_https else f'http://{local_ip}:5000'

def generate_order_pdf(order):
    """Generate PDF for order statement"""
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2E4053'),
        spaceAfter=10,
        alignment=TA_CENTER
    )
    
    # Title
    elements.append(Paragraph("Order Statement", title_style))
    elements.append(Spacer(1, 0.2*inch))
    
    # Order Info
    now = datetime.now()
    order_info = [
        ['Order Number:', f"#{order.id}"],
        ['Order Date & Time:', order.timestamp.strftime('%d-%m-%Y %I:%M %p')],
        ['PDF Generated:', now.strftime('%d-%m-%Y %I:%M:%S %p')],
        ['Customer Name:', order.customer.name if order.customer else 'Guest'],
        ['Customer Phone:', order.customer.phone_number if order.customer else 'N/A'],
        ['Payment Method:', order.payment_method],
        ['Payment Status:', order.payment_status.upper()],
        ['Order Status:', order.status.upper()],
    ]
    
    info_table = Table(order_info, colWidths=[2*inch, 3.5*inch])
    info_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ECF0F1')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 0.3*inch))
    
    # Items Table
    elements.append(Paragraph("Order Items", styles['Heading2']))
    items_data = [['Item Name', 'Quantity', 'Price per Item', 'Total']]
    for item in order.items:
        total_price = item.price * item.quantity
        items_data.append([
            item.menu_item.name,
            str(item.quantity),
            f"Rs.{item.price:.2f}",
            f"Rs.{total_price:.2f}"
        ])
    
    # Add summary rows
    subtotal = sum(item.price * item.quantity for item in order.items)
    tax = subtotal * 0.05
    items_data.append(['', '', 'Subtotal:', f"Rs.{subtotal:.2f}"])
    items_data.append(['', '', 'Tax (5%):', f"Rs.{tax:.2f}"])
    items_data.append(['', '', 'Total:', f"Rs.{order.total_amount:.2f}"])
    
    items_table = Table(items_data, colWidths=[2.5*inch, 1*inch, 1.5*inch, 1.5*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498DB')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        ('GRID', (0, 0), (-1, -4), 1, colors.black),
        ('BACKGROUND', (0, -3), (-1, -1), colors.HexColor('#ECF0F1')),
        ('FONTNAME', (0, -3), (-1, -1), 'Helvetica-Bold'),
        ('GRID', (0, -3), (-1, -1), 1, colors.black),
        ('ALIGN', (2, -3), (-1, -1), 'RIGHT'),
    ]))
    elements.append(Spacer(1, 0.1*inch))
    elements.append(items_table)
    
    # Build PDF
    doc.build(elements)
    pdf_buffer.seek(0)
    return pdf_buffer

def generate_receipt_pdf(order):
    """Generate PDF receipt for customers"""
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#27AE60'),
        spaceAfter=8,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    # Header
    elements.append(Paragraph("Sadakathullahappa College Canteen", title_style))
    elements.append(Paragraph("Order Receipt", styles['Heading2']))
    elements.append(Spacer(1, 0.2*inch))
    
    # Receipt Info
    now = datetime.now()
    receipt_info = [
        ['Receipt #:', f"#{order.id}"],
        ['Order Date:', order.timestamp.strftime('%d-%m-%Y')],
        ['Order Time:', order.timestamp.strftime('%I:%M %p')],
        ['PDF Generated:', now.strftime('%d-%m-%Y %I:%M:%S %p')],
        ['Customer:', order.customer.name if order.customer else 'Guest'],
        ['Phone:', order.customer.phone_number if order.customer else 'N/A'],
    ]
    
    receipt_table = Table(receipt_info, colWidths=[1.5*inch, 3.5*inch])
    receipt_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    elements.append(receipt_table)
    elements.append(Spacer(1, 0.15*inch))
    
    # Items
    elements.append(Paragraph("Items Ordered", styles['Heading3']))
    items_data = [['Item', 'Qty', 'Price', 'Total']]
    for item in order.items:
        total_price = item.price * item.quantity
        items_data.append([
            item.menu_item.name[:20],
            str(item.quantity),
            f"Rs.{item.price:.0f}",
            f"Rs.{total_price:.0f}"
        ])
    
    items_table = Table(items_data, colWidths=[2.5*inch, 0.7*inch, 0.9*inch, 1*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#27AE60')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 0.15*inch))
    
    # Summary
    subtotal = sum(item.price * item.quantity for item in order.items)
    tax = subtotal * 0.05
    summary_data = [
        ['Subtotal:', f"Rs.{subtotal:.2f}"],
        ['Tax (5%):', f"Rs.{tax:.2f}"],
        ['Total:', f"Rs.{order.total_amount:.2f}"],
    ]
    
    summary_table = Table(summary_data, colWidths=[3.5*inch, 1.5*inch])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#D5DBDB')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.15*inch))
    
    # Footer
    elements.append(Paragraph("Thank you for your order!", styles['Normal']))
    elements.append(Paragraph("Payment Status: " + order.payment_status.upper(), styles['Normal']))
    
    # Build PDF
    doc.build(elements)
    pdf_buffer.seek(0)
    return pdf_buffer


def reset_daily_stocks():
    """Reset available_count to daily_stock if the date has changed"""
    from datetime import datetime
    today = datetime.utcnow().date()
    
    # Find items that haven't been reset today
    items_to_reset = MenuItem.query.filter(MenuItem.last_reset_date < today).all()
    
    if items_to_reset:
        for item in items_to_reset:
            item.available_count = item.daily_stock
            item.last_reset_date = today
        db.session.commit()
        print(f"Reset stock for {len(items_to_reset)} items.")

app = Flask(__name__)

# Database configuration
# On Render, DATABASE_URL is set automatically (PostgreSQL)
# Locally, it uses SQLite (no MySQL required)
database_url = os.getenv('DATABASE_URL', '')
if database_url:
    # Render provides postgres:// but SQLAlchemy needs postgresql://
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Local SQLite (easier for development)
    # Check if MySQL is configured in environment variables
    db_user = os.getenv('DB_USER', '')
    db_password = os.getenv('DB_PASSWORD', '')
    db_host = os.getenv('DB_HOST', '')
    db_name = os.getenv('DB_NAME', '')
    db_port = os.getenv('DB_PORT', '3306')
    
    if db_user and db_host:
        # Use MySQL if credentials provided
        app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{db_user}:{quote_plus(db_password)}@{db_host}:{db_port}/{db_name}'
    else:
        # Use SQLite (default, no setup needed)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///menu_db.sqlite'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-change-in-production')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Serve static files in production
if os.environ.get('FLASK_ENV') == 'production':
    from flask import send_from_directory
    @app.route('/static/<path:filename>')
    def static_files(filename):
        return send_from_directory('static', filename)

# Initialize database
init_db(app)

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # type: ignore

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('admin'))
        
        return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Razorpay keys removed


@app.route('/')
def menu():
    """Customer-facing menu display"""
    # Reset stock if it's a new day
    reset_daily_stocks()
    
    items = MenuItem.query.filter(MenuItem.available == True, MenuItem.available_count > 0).all()
    categories_query = db.session.query(MenuItem.category).filter(MenuItem.available == True, MenuItem.available_count > 0).distinct().all()
    # Ensure categories are clean
    categories = [cat[0].strip() for cat in categories_query if cat[0]]

    # Ensure 'Drinks' is in categories if it exists in DB
    if 'Drinks' not in categories:
        has_drinks = MenuItem.query.filter_by(category='Drinks').first()
        if has_drinks:
            categories.append('Drinks')

    return render_template('menu.html', items=items, categories=categories)

@app.route('/admin')
@login_required
def admin():
    """Admin dashboard"""
    items = MenuItem.query.all()
    low_stock_items = MenuItem.query.filter(MenuItem.available_count > 0, MenuItem.available_count <= 5).all()
    out_of_stock_items = MenuItem.query.filter(MenuItem.available_count == 0).all()
    return render_template('admin.html', items=items, low_stock_items=low_stock_items, out_of_stock_items=out_of_stock_items)

@app.route('/admin/add', methods=['GET', 'POST'])
@login_required
def add_item():
    """Add new menu item"""
    if request.method == 'POST':
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Ensure directory exists
                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                image_url = f'images/{filename}'

        new_item = MenuItem(  # type: ignore
            name=request.form['name'],
            category=request.form['category'],
            description=request.form['description'],
            price=float(request.form['price']),
            available=request.form.get('available') == 'on',
            image_url=image_url,
            daily_stock=int(request.form.get('daily_stock', 50)),
            available_count=int(request.form.get('daily_stock', 50))
        )
        db.session.add(new_item)
        db.session.commit()
        return redirect(url_for('admin'))
    return render_template('add_item.html')

@app.route('/admin/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_item(id):
    """Edit existing menu item"""
    item = MenuItem.query.get_or_404(id)
    if request.method == 'POST':
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                if not os.path.exists(UPLOAD_FOLDER):
                    os.makedirs(UPLOAD_FOLDER)
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                item.image_url = f'images/{filename}'

        item.name = request.form['name']
        item.category = request.form['category']
        item.description = request.form['description']
        item.price = float(request.form['price'])
        item.available = request.form.get('available') == 'on'
        item.daily_stock = int(request.form.get('daily_stock', item.daily_stock))
        item.available_count = int(request.form.get('available_count', item.available_count))
        db.session.commit()
        return redirect(url_for('admin'))
    return render_template('edit_item.html', item=item)

@app.route('/admin/delete/<int:id>')
@login_required
def delete_item(id):
    """Delete menu item"""
    item = MenuItem.query.get_or_404(id)
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for('admin'))

# ===== CART AND CHECKOUT ROUTES =====

@app.route('/cart/add/<int:id>', methods=['POST'])
def add_to_cart(id):
    """Add item to cart"""
    item = MenuItem.query.get_or_404(id)
    
    # Initialize cart in session if it doesn't exist
    if 'cart' not in session:
        session['cart'] = {}
    
    # Get quantity from form, default to 1
    quantity = int(request.form.get('quantity', 1))
    
    # Add or update item in cart
    item_id = str(id)
    if item_id in session['cart']:
        session['cart'][item_id]['quantity'] += quantity
    else:
        session['cart'][item_id] = {
            'name': item.name,
            'price': item.price,
            'quantity': quantity
        }
    
    # Mark session as modified to ensure it's saved
    session.modified = True
    
    return redirect(url_for('view_cart'))

@app.route('/api/cart/add/<int:id>', methods=['POST'])
def api_add_to_cart(id):
    """Add item to cart via AJAX and return JSON"""
    try:
        item = MenuItem.query.get_or_404(id)
        
        if 'cart' not in session:
            session['cart'] = {}
        
        # Get data from JSON or form
        if request.is_json:
            data = request.get_json()
            quantity = int(data.get('quantity', 1))
        else:
            quantity = int(request.form.get('quantity', 1))
        
        # Check stock
        if item.available_count < quantity:
            return jsonify({'success': False, 'error': 'Not enough stock'}), 400
            
        item_id = str(id)
        if item_id in session['cart']:
            session['cart'][item_id]['quantity'] += quantity
        else:
            session['cart'][item_id] = {
                'name': item.name,
                'price': item.price,
                'quantity': quantity
            }
        
        session.modified = True
        
        # Total items in cart (unique items)
        cart_count = len(session['cart'])
        
        return jsonify({
            'success': True, 
            'cart_count': cart_count,
            'message': f'{item.name} added to cart!'
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/cart')
def view_cart():
    """Display cart page"""
    cart = session.get('cart', {})
    
    # Fetch available stock for each cart item
    stock_info = {}
    for item_id in cart:
        menu_item = MenuItem.query.get(int(item_id))
        if menu_item:
            stock_info[item_id] = menu_item.available_count
        else:
            stock_info[item_id] = 0
    
    # Calculate totals
    subtotal = sum(item['price'] * item['quantity'] for item in cart.values())
    tax = subtotal * 0.05  # 5% tax
    total = subtotal + tax
    
    return render_template('cart.html', cart=cart, stock_info=stock_info, subtotal=subtotal, tax=tax, total=total)

@app.route('/cart/update/<int:id>', methods=['POST'])
def update_cart(id):
    """Update item quantity in cart"""
    cart = session.get('cart', {})
    item_id = str(id)
    
    if item_id in cart:
        quantity = int(request.form.get('quantity', 0))
        if quantity > 0:
            cart[item_id]['quantity'] = quantity
        else:
            # Remove item if quantity is 0
            del cart[item_id]
        
        session['cart'] = cart
        session.modified = True
    
    return redirect(url_for('view_cart'))

@app.route('/cart/remove/<int:id>')
def remove_from_cart(id):
    """Remove item from cart"""
    cart = session.get('cart', {})
    item_id = str(id)
    
    if item_id in cart:
        del cart[item_id]
        session['cart'] = cart
        session.modified = True
    
    return redirect(url_for('view_cart'))

@app.route('/checkout')
def checkout():
    """Display checkout page"""
    cart = session.get('cart', {})
    
    # Redirect to cart if empty
    if not cart:
        return redirect(url_for('view_cart'))
    
    # Calculate totals
    subtotal = sum(item['price'] * item['quantity'] for item in cart.values())
    tax = subtotal * 0.05  # 5% tax
    total = subtotal + tax
    
    return render_template('checkout.html', 
                         cart=cart, 
                         subtotal=subtotal, 
                         tax=tax, 
                         total=total)

@app.route('/order/confirm', methods=['POST'])
def confirm_order():
    """Process and confirm order - for CASH payments (and fallback for UPI form POST)"""
    try:
        cart = session.get('cart', {})
        print(f"[ORDER] confirm_order called. Cart items: {len(cart)}, IP: {request.remote_addr}")
        
        if not cart:
            print("[ORDER] ERROR: Cart is empty, redirecting to menu")
            return redirect(url_for('menu'))
        
        # Get form data
        customer_name = request.form.get('customer_name')
        phone_number = request.form.get('phone_number')
        payment_method = request.form.get('payment_method', 'Cash')
        
        print(f"[ORDER] Customer: {customer_name}, Phone: {phone_number}, Method: {payment_method}")
        
        if not phone_number or not customer_name:
            print("[ORDER] ERROR: Missing name or phone")
            return redirect(url_for('checkout'))

        # Get or create customer
        customer = Customer.query.filter_by(phone_number=phone_number).first()
        if not customer:
            customer = Customer(phone_number=phone_number, name=customer_name)  # type: ignore
            db.session.add(customer)
            db.session.flush()
        else:
            customer.name = customer_name
            db.session.flush()

        # Calculate total
        total_amount = sum(item['price'] * item['quantity'] for item in cart.values())
        total_amount *= 1.05  # Add 5% tax
        
        # Determine payment status based on method
        if payment_method == 'Cash':
            p_status = 'not_required'
        else:
            p_status = 'success'
        
        # Create order
        new_order = Order(
            customer_id=customer.id,
            total_amount=total_amount,
            payment_method=payment_method,
            status='confirmed',
            payment_status=p_status
        )
        db.session.add(new_order)
        db.session.flush()
        
        print(f"[ORDER] Created Order #{new_order.id}, Total: Rs.{total_amount:.2f}")
        
        # Add order items and decrement stock
        for item_id, item_data in cart.items():
            menu_item = MenuItem.query.get(int(item_id))
            if menu_item:
                menu_item.available_count = max(0, menu_item.available_count - item_data['quantity'])
                
            order_item = OrderItem(
                order_id=new_order.id,
                menu_item_id=int(item_id),
                quantity=item_data['quantity'],
                price=item_data['price']
            )
            db.session.add(order_item)
        
        db.session.commit()
        print(f"[ORDER] SUCCESS: Order #{new_order.id} saved to database!")
        
        # Clear cart
        session.pop('cart', None)
        session.modified = True
        
        return redirect(url_for('order_success', order_id=new_order.id))
    
    except Exception as e:
        print(f"[ORDER] EXCEPTION: {e}")
        db.session.rollback()
        return redirect(url_for('menu'))

@app.route('/order/success/<int:order_id>')
def order_success(order_id):
    """Display order success page"""
    order = Order.query.get_or_404(order_id)
    return render_template('order_success.html', order=order)

# ===== PAYMENT GATEWAY ROUTES =====

@app.route('/api/payment/create-order', methods=['POST'])
def create_payment_order():
    """Create mock order for online payment"""
    
    try:
        data = request.get_json()
        customer_name = data.get('customer_name')
        phone_number = data.get('phone_number')
        payment_method = data.get('payment_method')
        
        # Mock UPI specific fields
        upi_id = data.get('upi_id')
        upi_pin = data.get('upi_pin')
        
        if not phone_number or not customer_name:
            return jsonify({'error': 'Name and Phone number are required'}), 400
            
        cart = session.get('cart', {})
        if not cart:
            return jsonify({'error': 'Cart is empty'}), 400
        
        # Calculate total
        total_amount = sum(item['price'] * item['quantity'] for item in cart.values())
        total_amount *= 1.05  # Add 5% tax
        
        # Convert to paise
        amount_in_paise = int(total_amount * 100)
        
        key_to_use = None
        order_id = None
        
        if payment_method == 'UPI_Mock':
            # Simple Mock Validation
            if not upi_id or not upi_pin:
                 return jsonify({'error': 'UPI ID and PIN are required'}), 400
            if upi_pin != '1234':
                 return jsonify({'error': 'Invalid UPI PIN'}), 400
            
            order_id = f"order_upi_mock_{int(time.time())}"
            key_to_use = 'mock_upi_key'
        else:
            # Generate generic mock order for anything else (shouldn't really happen with frontend restrictions)
            order_id = f"order_mock_{int(time.time())}"
            key_to_use = 'rzp_test_MOCK_KEY_ID'
            print(f"Creating MOCK payment order: {order_id}")
        
        # Store order info in session
        session['pending_order'] = {
            'razorpay_order_id': order_id,
            'customer_name': customer_name,
            'phone_number': phone_number,
            'payment_method': payment_method,
            'amount': total_amount,
            'is_mock': True,
            'upi_id': upi_id if payment_method == 'UPI_Mock' else None
        }
        session.modified = True # Ensure session is saved
        
        return jsonify({
            'order_id': order_id,
            'amount': amount_in_paise,
            'currency': 'INR',
            'key_id': key_to_use
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/payment/verify', methods=['POST'])
def verify_payment():
    """Verify payment and create order in database"""
    # Get pending order info first to check if it's mock
    pending_order = session.get('pending_order')
    if not pending_order:
        return jsonify({'error': 'No pending order found'}), 400

    is_mock = pending_order.get('is_mock', False)

    try:
        data = request.get_json()
        payment_id = data.get('razorpay_payment_id')
        order_id = data.get('razorpay_order_id')
        signature = data.get('razorpay_signature')
        
        # Validate Order ID match
        if pending_order['razorpay_order_id'] != order_id:
            return jsonify({'error': 'Invalid order ID'}), 400

        # Always pass verification for mock
        # We don't verify signatures since we don't have a backend secret for real Razorpay anymore
        print(f"Verifying MOCK payment for order {order_id}")
        
        cart = session.get('cart', {})
        if not cart:
            return jsonify({'error': 'Cart is empty'}), 400
        
        # Get or create customer
        customer = Customer.query.filter_by(phone_number=pending_order['phone_number']).first()
        if not customer:
            customer = Customer(
                phone_number=pending_order['phone_number'],
                name=pending_order['customer_name']
            )
            db.session.add(customer)
            db.session.flush()
        else:
            # Update name if provided
            customer.name = pending_order['customer_name']
            db.session.flush()

        # Create order in database
        new_order = Order(
            customer_id=customer.id,
            total_amount=pending_order['amount'],
            payment_method=pending_order['payment_method'],
            status='confirmed',
            payment_id=payment_id,
            payment_order_id=order_id,
            payment_signature=signature,
            payment_status='success',
            upi_id=pending_order.get('upi_id'),
            upi_ref=f"ref_{int(time.time())}" if pending_order.get('upi_id') else None
        )
        db.session.add(new_order)
        db.session.flush()
        
        # Add order items and decrement stock
        for item_id, item_data in cart.items():
            # Get menu item to update stock
            menu_item = MenuItem.query.get(int(item_id))
            if menu_item:
                # Prevent going below 0
                menu_item.available_count = max(0, menu_item.available_count - item_data['quantity'])

            order_item = OrderItem(
                order_id=new_order.id,
                menu_item_id=int(item_id),
                quantity=item_data['quantity'],
                price=item_data['price']
            )
            db.session.add(order_item)
        
        db.session.commit()
        
        # Clear cart and pending order
        session.pop('cart', None)
        session.pop('pending_order', None)
        session.modified = True
        
        return jsonify({
            'success': True,
            'order_id': new_order.id,
            'redirect_url': url_for('payment_success', order_id=new_order.id)
        })
    
    except Exception as e:
        print(f"Payment verification and order creation error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/payment/success/<int:order_id>')
def payment_success(order_id):
    """Display payment success page"""
    order = Order.query.get_or_404(order_id)
    return render_template('payment_success.html', order=order)

@app.route('/payment/failed')
def payment_failed():
    """Display payment failure page"""
    return render_template('payment_failed.html')

# ===== PDF DOWNLOAD ROUTES =====

@app.route('/api/order/<int:order_id>/download-pdf')
@login_required
def download_order_pdf(order_id):
    """Download order statement as PDF (Admin only)"""
    order = Order.query.get_or_404(order_id)
    
    pdf_buffer = generate_order_pdf(order)
    
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Order_{order.id}_Statement.pdf'
    )

@app.route('/api/receipt/<int:order_id>/download-pdf')
def download_receipt_pdf(order_id):
    """Download receipt as PDF (Customer)"""
    order = Order.query.get_or_404(order_id)
    
    pdf_buffer = generate_receipt_pdf(order)
    
    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Receipt_{order.id}.pdf'
    )

# ===== ADMIN ORDERS ROUTES =====
def generate_admin_summary_pdf(start_date, end_date, total_orders, total_income, total_items_sold, item_sales, todays_orders):
    pdf_buffer = BytesIO()
    doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)
    elements = []

    styles = getSampleStyleSheet()
    header_style = ParagraphStyle('Header', parent=styles['Heading1'], fontSize=20, alignment=TA_CENTER, textColor=colors.HexColor('#2E86C1'))
    normal_style = styles['Normal']

    elements.append(Paragraph('Sadakathullah Appa Canteen - Daily Summary', header_style))
    elements.append(Spacer(1, 0.2*inch))

    # Calculate IST time (UTC + 5:30)
    now_ist = datetime.now() + timedelta(hours=5, minutes=30)

    summary_data = [
        ['Period:', f"{start_date.strftime('%d-%m-%Y')}"],
        ['Report Generated:', now_ist.strftime('%d-%m-%Y %I:%M %p')],
        ['Total Orders:', str(total_orders)],
        ['Total Revenue:', f"Rs. {total_income:.2f}"],
        ['Total Items Sold:', str(total_items_sold)],
    ]

    summary_table = Table(summary_data, colWidths=[3*inch, 3*inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F4D03F')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.black),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 10),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
    ]))

    elements.append(summary_table)
    elements.append(Spacer(1, 0.3*inch))

    elements.append(Paragraph('Top Selling Items (Quantity)', styles['Heading2']))
    if item_sales:
        data = [['Item', 'Quantity Sold']]
        for name, qty in item_sales:
            data.append([name, str(int(qty))])

        items_table = Table(data, colWidths=[3.5*inch, 2.5*inch])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2ECC71')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 10),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(items_table)
    else:
        elements.append(Paragraph('No items sold in this period yet.', normal_style))
        
    elements.append(Spacer(1, 0.4*inch))
    
    # Detailed Orders Log
    elements.append(Paragraph('Detailed Orders Log', styles['Heading2']))
    if todays_orders:
        log_data = [['Order #', 'Time', 'Customer', 'Items', 'Total Amount']]
        for order in todays_orders:
            time_str = order.timestamp.strftime('%I:%M %p')
            customer_name = order.customer.name if order.customer else 'Guest'
            items_count = sum(item.quantity for item in order.items)
            log_data.append([
                f"#{order.id}",
                time_str,
                customer_name,
                f"{items_count} items",
                f"Rs. {order.total_amount:.2f}"
            ])
            
        log_table = Table(log_data, colWidths=[0.8*inch, 1*inch, 2*inch, 1*inch, 1.2*inch])
        log_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#34495E')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('FONTNAME', (0,1), (-1,-1), 'Helvetica'),
            ('FONTSIZE', (0,0), (-1,-1), 9),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
        ]))
        elements.append(log_table)
    else:
        elements.append(Paragraph('No orders logged today.', normal_style))

    doc.build(elements)
    pdf_buffer.seek(0)
    return pdf_buffer


@app.route('/admin/orders/summary-pdf')
@login_required
def download_admin_summary_pdf():
    # Get today's date in IST
    now_ist = datetime.now() + timedelta(hours=5, minutes=30)
    today = now_ist.date()
    start_dt = datetime(today.year, today.month, today.day)
    end_dt = start_dt + timedelta(days=1)

    todays_orders = Order.query.filter(Order.timestamp >= start_dt, Order.timestamp < end_dt).all()
    total_orders = len(todays_orders)
    total_income = sum(order.total_amount for order in todays_orders)
    total_items_sold = sum(item.quantity for order in todays_orders for item in order.items)

    item_sales = db.session.query(MenuItem.name, func.sum(OrderItem.quantity).label('sold_qty')).join(
        OrderItem, MenuItem.id == OrderItem.menu_item_id
    ).join(
        Order, OrderItem.order_id == Order.id
    ).filter(
        Order.timestamp >= start_dt,
        Order.timestamp < end_dt
    ).group_by(MenuItem.id).order_by(func.sum(OrderItem.quantity).desc()).all()

    pdf_buffer = generate_admin_summary_pdf(start_dt, end_dt - timedelta(days=1), total_orders, total_income, total_items_sold, item_sales, todays_orders)

    return send_file(
        pdf_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=f'Admin_Summary_{today.strftime("%Y%m%d")}.pdf'
    )


@app.route('/admin/orders')
@login_required
def admin_orders():
    """View all orders in admin panel"""
    orders = Order.query.order_by(Order.timestamp.desc()).all()
    print(f"[DEBUG] admin_orders: Found {len(orders)} orders")
    for o in orders:
        print(f"  Order #{o.id} - {o.status} - {o.payment_method} - {o.timestamp}")
    low_stock_items = MenuItem.query.filter(MenuItem.available_count > 0, MenuItem.available_count <= 5).all()
    out_of_stock_items = MenuItem.query.filter(MenuItem.available_count == 0).all()
    return render_template('admin_orders.html', orders=orders, low_stock_items=low_stock_items, out_of_stock_items=out_of_stock_items)

@app.route('/api/debug/orders')
def debug_orders():
    """Debug: check orders in JSON"""
    orders = Order.query.order_by(Order.timestamp.desc()).all()
    return jsonify([{
        'id': o.id, 'total': o.total_amount, 'status': o.status,
        'method': o.payment_method, 'time': str(o.timestamp),
        'customer': o.customer.name if o.customer else 'N/A',
        'items': len(o.items)
    } for o in orders])


# ===== QR CODE ROUTES =====


@app.route('/qr')
def qr_code():
    """Display the single QR code page"""
    custom_url = request.args.get('custom_url', '')

    if custom_url:
        target_url = custom_url
    else:
        # Point to the welcome page which has Role Selection
        base_url = get_public_url()
        target_url = f"{base_url}"

    public_url = get_public_url()
    
    return render_template('qr_code.html',
                         target_url=target_url,
                         public_url=public_url,
                         custom_url=custom_url)

@app.route('/qr/generate')
def generate_qr():
    """Generate the single QR code image"""
    custom_url = request.args.get('custom_url', '')

    if custom_url:
        target_url = custom_url
    else:
        # Point to the welcome page
        base_url = get_public_url()
        target_url = f"{base_url}"

    # Create QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(target_url)  # Changed from menu_url to target_url
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    img_io = BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)

    return send_file(img_io, mimetype='image/png')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    local_ip = get_local_ip()
    public_url_env = os.getenv('PUBLIC_URL', '').strip().rstrip('/')

    print(f"\nServer running:")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{local_ip}:{port}  <- Use this for phones on same WiFi")

    if public_url_env:
        display_public = public_url_env
        if not public_url_env.startswith(('http://', 'https://')):
            display_public = f"https://{public_url_env}"
        print(f"  Public:  {display_public}  <- Use this for any phone on any network")
    
    # For local development only - remove for production
    if os.environ.get('FLASK_ENV') != 'production':
        import subprocess
        import threading
        cf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cloudflared.exe')
        
        # Only run in the main worker to prevent duplicate tunnels
        if os.path.exists(cf_path) and os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            try:
                print("\n  [Cloudflare] Starting tunnel for direct access without warnings...")
                # Start tunnel and get url inline
                process = subprocess.Popen(
                    [cf_path, 'tunnel', '--url', f'http://localhost:{port}'],
                    stderr=subprocess.PIPE, stdout=subprocess.PIPE, text=True
                )
                
                url_found = []
                def read_stderr():
                    for line in process.stderr:
                        if 'trycloudflare.com' in line and 'https://' in line:
                            url_start = line.find('https://')
                            url_end = line.find('.com', url_start) + 4
                            url_found.append(line[url_start:url_end])
                            break
                
                t = threading.Thread(target=read_stderr)
                t.start()
                t.join(timeout=5)
                
                if url_found:
                    os.environ['PUBLIC_URL'] = url_found[0]
                    print(f"  [Cloudflare Tunnel] Public URL: {url_found[0]}")
                    print(f"  ✅ NO 'Visit Site' warning! Direct app access from any phone.\n")
            except Exception as e:
                print(f"  [Cloudflare Error]: {e}")

        elif not os.environ.get('PUBLIC_URL'):
            # Fallback to ngrok if we didn't get a cloudflare URL yet
            try:
                import requests
                response = requests.get('http://localhost:4040/api/tunnels', timeout=5)
                if response.status_code == 200:
                    tunnels = response.json()['tunnels']
                    if tunnels:
                        public_url = tunnels[0]['public_url']
                        os.environ['PUBLIC_URL'] = public_url
                        print(f"\n  [Ngrok Tunnel] Public URL: {public_url}")
                    else:
                        print(f"  [Ngrok Tunnel]: No tunnels found - start ngrok manually")
                else:
                    print(f"  [Ngrok Tunnel]: Not running - start .\ngrok.exe http 5000 in another terminal")
            except Exception as e:
                print(f"  [Ngrok Tunnel Failed]: {e}")
                print(f"  Falling back to local-only mode. Start ngrok manually for public access.\n")
        
        app.run(debug=True, host='0.0.0.0', port=port)
    else:
        # Production mode - no debug, no cloudflare tunnel
        app.run(debug=False, host='0.0.0.0', port=port)
