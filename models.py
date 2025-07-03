from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer
from db import Base

Base = declarative_base()

class Skin(Base):
    __tablename__ = "skins"
    id = Column(Integer, primary_key=True)
    category = Column(String(50))
    item = Column(String(50))
    name = Column(String(100))
    condition = Column(String(50))
    price = Column(String(50))
    img = Column(Text)

class Inventory(Base):
    __tablename__ = "inventories"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    skin_id = Column(Integer)

class SellRequest(Base):
    __tablename__ = "sell_requests"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    name = Column(String(100))
    condition = Column(String(50))
    price = Column(String(50))
    img = Column(Text)
    status = Column(String(20))  # pending/confirmed/cancelled

class BuyRequest(Base):
    __tablename__ = "buy_requests"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    skin_id = Column(Integer)
    photo_id = Column(Text)
    status = Column(String(20))  # pending/confirmed/cancelled

class Admin(Base):
    __tablename__ = "admins"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
