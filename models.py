import os

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta

def get_ist_now():
    """Return current time in IST (UTC+5:30)"""
    ist = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist).replace(tzinfo=None)

db = SQLAlchemy()
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class User(UserMixin, db.Model):
    """Admin user model"""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class MenuItem(db.Model):
    """Database model for menu items"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    available = db.Column(db.Boolean, default=True)
    image_url = db.Column(db.String(200), nullable=True)  # Path to food image
    
    # Stock management fields
    daily_stock = db.Column(db.Integer, default=50) # Initial daily reset count
    available_count = db.Column(db.Integer, default=50) # Current remaining items
    last_reset_date = db.Column(db.Date, default=lambda: datetime.utcnow().date())

    def __repr__(self):
        return f'<MenuItem {self.name} - Stock: {self.available_count}/{self.daily_stock}>'

class Customer(db.Model):
    """Database model for customers"""
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(15), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    
    # Relationship with orders
    orders = db.relationship('Order', backref='customer', lazy=True)

    def __repr__(self):
        return f'<Customer {self.phone_number}>'

class Order(db.Model):
    """Database model for customer orders"""
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True) # Linked to customer
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, completed, cancelled
    payment_method = db.Column(db.String(50))  # Cash, UPI, Card, UPI_Mock
    timestamp = db.Column(db.DateTime, default=get_ist_now)
    
    # Payment gateway fields
    payment_id = db.Column(db.String(100), nullable=True)  # Razorpay payment ID
    payment_order_id = db.Column(db.String(100), nullable=True)  # Razorpay order ID
    payment_signature = db.Column(db.String(200), nullable=True)  # Payment verification signature
    payment_status = db.Column(db.String(20), default='pending')  # pending, success, failed
    
    # Mock UPI fields
    upi_id = db.Column(db.String(100), nullable=True)
    upi_ref = db.Column(db.String(100), nullable=True)
    
    # Relationship with order items
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Order {self.id} - {self.payment_status}>'

class OrderItem(db.Model):
    """Database model for individual items in an order"""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey('menu_item.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    price = db.Column(db.Float, nullable=False)  # Price at time of order
    
    # Relationship with menu item
    menu_item = db.relationship('MenuItem', backref='order_items')

    def __repr__(self):
        return f'<OrderItem {self.id} - Order {self.order_id}>'

def init_db(app):
    """Initialize database and create sample data"""
    db.init_app(app)
    
    with app.app_context():
        db.create_all()
        
        # Check if database is empty
        if MenuItem.query.count() == 0:
            # Indian Menu Items
            sample_items = [
                # Breakfast Items
                MenuItem(
                    name="Idli (3 pcs)",
                    category="Breakfast",
                    description="Soft steamed rice cakes served with sambar and coconut chutney",
                    price=25.00,
                    available=True,
                    image_url="images/south-indian-idli.jpg",
                    daily_stock=50,
                    available_count=50
                ),
                MenuItem(
                    name="Masala Dosa",
                    category="Breakfast",
                    description="Crispy rice crepe filled with spiced potato masala, served with sambar and chutney",
                    price=40.00,
                    available=True,
                    image_url="images/masala_dos.jpg",
                    daily_stock=20,
                    available_count=20
                ),
                MenuItem(
                    name="Poori Bhaji (2 pcs)",
                    category="Breakfast",
                    description="Fluffy deep-fried bread served with spiced potato curry",
                    price=35.00,
                    available=True,
                    image_url="images/bhaji.jpg",
                    daily_stock=30,
                    available_count=30
                ),
                MenuItem(
                    name="Upma",
                    category="Breakfast",
                    description="Savory semolina porridge with vegetables and spices",
                    price=30.00,
                    available=True,
                    image_url="images/upma_image.jpg",
                    daily_stock=25,
                    available_count=25
                ),
                MenuItem(
                    name="Vada (2 pcs)",
                    category="Breakfast",
                    description="Crispy lentil fritters served with sambar and chutney",
                    price=20.00,
                    available=True,
                    image_url="images/vada.jpg",
                    daily_stock=40,
                    available_count=40
                ),

                # Lunch Items
                MenuItem(
                    name="Chicken Biryani",
                    category="Lunch",
                    description="Aromatic basmati rice cooked with tender chicken pieces and spices, served with raita",
                    price=80.00,
                    available=True,
                    image_url="images/c_biriyani.jpg",
                    daily_stock=50,
                    available_count=50
                ),
                MenuItem(
                    name="Vegetable Biryani",
                    category="Lunch",
                    description="Fragrant basmati rice with mixed vegetables and aromatic spices",
                    price=60.00,
                    available=True,
                    image_url="images/veg_biriyani.jpg",
                    daily_stock=40,
                    available_count=40
                ),
                MenuItem(
                    name="Curd Rice",
                    category="Lunch",
                    description="Cooling rice mixed with yogurt, tempered with mustard seeds and curry leaves",
                    price=35.00,
                    available=True,
                    image_url="images/curd-rice.jpg",
                    daily_stock=30,
                    available_count=30
                ),
                MenuItem(
                    name="Sambar Rice",
                    category="Lunch",
                    description="Rice mixed with tangy lentil vegetable stew",
                    price=40.00,
                    available=True,
                    image_url="images/instant-pot-sambar-rice-sambar-sadam-1024x1024.jpg",
                    daily_stock=35,
                    available_count=35
                ),
                MenuItem(
                    name="Meals (Veg Thali)",
                    category="Lunch",
                    description="Complete meal with rice, sambar, rasam, 2 vegetables, curd, and chapati",
                    price=70.00,
                    available=True,
                    image_url="images/meals_veg.jpg",
                    daily_stock=20,
                    available_count=20
                ),
                MenuItem(
                    name="Chicken Curry with Rice",
                    category="Lunch",
                    description="Spicy chicken curry served with steamed rice",
                    price=85.00,
                    available=True,
                    image_url="images/chicken_curry_rice.jpg",
                    daily_stock=30,
                    available_count=30
                ),
                MenuItem(
                    name="Dal Fry with Rice",
                    category="Lunch",
                    description="Tempered yellow lentils served with steamed rice",
                    price=50.00,
                    available=True,
                    image_url="images/dal_rice.jpg",
                    daily_stock=25,
                    available_count=25
                ),

                # Tea Items (Snacks & Beverages)
                MenuItem(
                    name="Samosa (2 pcs)",
                    category="Tea",
                    description="Crispy pastry filled with spiced potatoes and peas",
                    price=20.00,
                    available=True,
                    image_url="images/samso.jpg",
                    daily_stock=100,
                    available_count=100
                ),
                MenuItem(
                    name="Veg Puff",
                    category="Tea",
                    description="Flaky puff pastry filled with spiced vegetables",
                    price=25.00,
                    available=True,
                    image_url="images/veg_puffs.jpg",
                    daily_stock=40,
                    available_count=40
                ),
                MenuItem(
                    name="Paneer Pakoda",
                    category="Tea",
                    description="Cottage cheese fritters in gram flour batter",
                    price=35.00,
                    available=True,
                    image_url="images/paneer.jpg",
                    daily_stock=30,
                    available_count=30
                ),
                MenuItem(
                    name="Bread Omelet",
                    category="Tea",
                    description="Classic egg omelet served with bread slices",
                    price=30.00,
                    available=True,
                    image_url="images/bread_omellete.jpg",
                    daily_stock=30,
                    available_count=30
                ),
                MenuItem(
                    name="Filter Coffee",
                    category="Tea",
                    description="Traditional South Indian coffee with frothy milk",
                    price=15.00,
                    available=True,
                    image_url="images/filter-coffee-recipe-1.webp",
                    daily_stock=100,
                    available_count=100
                ),
                MenuItem(
                    name="Chai (Tea)",
                    category="Tea",
                    description="Hot Indian spiced tea",
                    price=10.00,
                    available=True,
                    image_url="images/taea.jpg",
                    daily_stock=200,
                    available_count=200
                ),
                MenuItem(
                    name="Buttermilk",
                    category="Tea",
                    description="Refreshing spiced yogurt drink",
                    price=15.00,
                    available=True,
                    image_url="images/butter_milk.jpg",
                    daily_stock=50,
                    available_count=50
                ),

                # Drinks Category
                MenuItem(
                    name="Cold Coffee",
                    category="Drinks",
                    description="Iced coffee with milk and sugar for quick energy",
                    price=35.00,
                    available=True,
                    image_url="images/cold_coffee.jpg",
                    daily_stock=80,
                    available_count=80
                ),
                MenuItem(
                    name="Nimbu Pani",
                    category="Drinks",
                    description="Refreshing lemon drink with a pinch of salt and sugar",
                    price=20.00,
                    available=True,
                    image_url="images/nimbu_pani.jpg",
                    daily_stock=100,
                    available_count=100
                ),
                MenuItem(
                    name="Masala Chai",
                    category="Drinks",
                    description="Hot spiced tea made with milk and aromatic spices",
                    price=15.00,
                    available=True,
                    image_url="images/masala_chai.jpg",
                    daily_stock=150,
                    available_count=150
                ),
                MenuItem(
                    name="Lemon Soda",
                    category="Drinks",
                    description="Chilled soda with lemon, mint and a hint of sugar",
                    price=25.00,
                    available=True,
                    image_url="images/lemon_soda.jpg",
                    daily_stock=90,
                    available_count=90
                ),
                MenuItem(
                    name="Mint Mojito",
                    category="Drinks",
                    description="Mint and lime cooler (non-alcoholic)",
                    price=30.00,
                    available=True,
                    image_url="images/mint_mojito.jpg",
                    daily_stock=60,
                    available_count=60
                ),
            ]
            
            db.session.add_all(sample_items)
            db.session.commit()
            print("Database initialized with full Indian menu!")
        
        # Create default admin user if not exists
        admin_username = os.getenv('ADMIN_USERNAME', 'admin')
        admin_password = os.getenv('ADMIN_PASSWORD', 'password123')

        if User.query.filter_by(username=admin_username).first() is None:
            admin = User(username=admin_username)
            admin.set_password(admin_password)
            db.session.add(admin)
            db.session.commit()
            print(f"Default admin user created ({admin_username}/{admin_password})")

        # Drinks/Juice items are managed manually via admin panel
        # No auto-creation on startup
