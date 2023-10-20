from sqlalchemy import Column, Integer, String, Boolean, create_engine 
from sqlalchemy.ext.declarative import declarative_base 
from sqlalchemy.orm import sessionmaker, Session
from .file_paths import DATABASE_FILEPATH
from typing import List 
import os 

Base = declarative_base()


class DatabaseManager:
    
    class DetectorDeployment(Base):
        """
        Schema for the the `detector_deployments` database table
        """
        __tablename__ = "detector_deployments"
        
        id = Column(Integer, primary_key=True)
        detector_id = Column(String)
        api_token = Column(String)
        deployment_created = Column(Boolean)
        
    class IQECache(Base):
        """
        Schema for the `iqe_cache` database table 
        """
        __tablename__ = "iqe_cache"
    
    def __init__(self):
        self._engine = create_engine(f"sqlite:///{self.validate_filepath(DATABASE_FILEPATH)}")
        self.session = sessionmaker(bind=self.engine)
        
        tables = ["detector_deployments", "iqe_cache"]
        self._create_tables(tables=tables)
        
    @staticmethod
    def validate_filepath(filepath: str) -> str:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Invalid filepath: {filepath}")
        
        return filepath 
    
    def create_database_record(self, record) -> None:
        with Session(self._engine) as session:
            session.add(record)
            session.commit() 
        
        
    def _create_tables(self, tables: List[str]) -> None:
        """
        Checks if the database tables exist and if they don't create them
        :param tables: A list of database tables in the database 
        
        :return: None 
        :rtype: None 
        """
        for table_name in tables:
            if not self.engine.dialect.has_table(self._engine, table_name):
                Base.metadata.create_all(self._engine)
                
                
if __name__=="__main__":
    db_manager = DatabaseManager()
                
    