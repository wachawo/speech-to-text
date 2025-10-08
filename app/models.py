#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine
from sqlalchemy import Column, Integer, String, DateTime

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass
load_dotenv('../.env')

POSTGRES_HOST=os.getenv('POSTGRES_HOST', 'cgevents_postgres')
POSTGRES_PORT=int(os.getenv('POSTGRES_PORT', '5432'))
POSTGRES_DB=os.getenv('POSTGRES_DB', 'default')
POSTGRES_USER=os.getenv('POSTGRES_USER', 'postgres')
POSTGRES_PASSWORD=os.getenv('POSTGRES_PASSWORD', '')
POSTGRES_URL = f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

engine = create_engine(
    POSTGRES_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Report(Base):
    __tablename__ = "reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    app = Column(String(50), nullable=False)
    cluster = Column(String(100), nullable=False)
    route = Column(String(255), nullable=False)
    username = Column(String(100), nullable=False)


def main():
    pass

if __name__ == '__main__':
    main()
