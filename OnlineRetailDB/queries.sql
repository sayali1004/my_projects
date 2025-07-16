CREATE DATABASE OnlineRetailDB;

-- USE THE DATABASE
USE OnlineRetailDB

-- CREATE TABLE CUSTOMERS
CREATE TABLE Customers (
    CustomerID INT AUTO_INCREMENT PRIMARY KEY,
    FirstName VARCHAR(50),
    LastName VARCHAR(50),
    Email VARCHAR(100),
    Phone VARCHAR(50),
    Address VARCHAR(200),
    City VARCHAR(50),
    State VARCHAR(50),
    ZipCode VARCHAR(50),
    Country VARCHAR(50),
    CreateAt DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- CREATE TABLE PRODUCTS 
CREATE TABLE Products(
	ProductID INT AUTO_INCREMENT PRIMARY KEY ,
    ProductName VARCHAR(50),
    CategoryID INT,
    Price DECIMAL(10,2),
 
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP

);
-- ALTER TABLE Products
ALTER TABLE Products
ADD Stock INT;

-- CREATE TABLE CATEGORY
CREATE TABLE Category(
	CategoryID INT AUTO_INCREMENT PRIMARY KEY ,
    CategoryName VARCHAR(100),
    Description VARCHAR(255)
);

-- CREATE TABLE ORDERS
CREATE TABLE Orders(
	OrderID INT AUTO_INCREMENT PRIMARY KEY ,
	CustomerID INT,
    TotalAmount DECIMAL(10,2),
    OrderDate DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(CustomerID) REFERENCES Customers(CustomerID)
    
);

-- CREATE TABLE ORDERITEMS
CREATE TABLE OrdersItems(
	OrderItemID INT AUTO_INCREMENT PRIMARY KEY ,
	OrderID INT,
    ProductID INT,
    Quantity INT,
	FOREIGN KEY(ProductID) REFERENCES Products(ProductID),
	FOREIGN KEY(OrderID) REFERENCES Orders(OrderID)

);

-- ALTER TABLE ORDERITEMS
ALTER TABLE OrdersItems
MODIFY COLUMN Price DECIMAL(10,2) AFTER Quantity;


-- Insert Sample Data into Categories table
INSERT INTO Category(CategoryName, Description) 
VALUES
('Electronics', 'Devices and Gadgets'),
('Clothing', 'Apparels and Accessories'),
('Books', 'Printed and Electronic Books');

-- Insert Sample Data into Products table
INSERT INTO Products(ProductName, CategoryID, Price, Stock) 
VALUES
('Smartphone', 1, 699.99, 50),
('Laptop', 1, 999.99, 30),
('T-shirt', 2, 19.99, 100),
('Jeans', 2, 49.99, 60),
('Fiction Novel', 3, 14.99, 200),
('Science Journal', 3, 29.99, 150);

-- Insert Sample Data into customers Table
INSERT INTO Customers(FirstName, LastName, Email, Phone, Address, City, State, ZipCode, Country) 
VALUES
('Sam', 'Joseph', 'sam.joseph@gmail.com', '123-456-7890', '123 Elm Rd', 'Springfield','IL', '92115', 'USA'),
('Tate', 'Lewis', 'tate.lewis@gmail.com', '673-456-7870', '5437 El Cajon Rd', 'San Ontonio','CA', '35815', 'USA'),
('Jane', 'Austin', 'jane.austin@gmail.com', '895-367-3217', '1651 University Ave', 'Binghamton','NY', '19423', 'USA'),
('John', 'Malik', 'john.malik@gmail.com', '663-406-1456', '3678 Fashion St', 'San Diego','CA', '93267', 'USA');

-- Insert more
INSERT INTO Customers(FirstName, LastName, Email, Phone, Address, City, State, ZipCode, Country) 
VALUES
('Alexa', 'K', 'Alexa.k@gmail.com', '809-123-0476', '562 Balboa Park Ave', 'Ithaca','NY', '41236', 'USA');

-- Describe Customers Table

SELECT * FROM Customers;

-- Insert Sample Data into Orders Table
INSERT INTO Orders(CustomerID, TotalAmount, OrderDate) 
VALUES
(1, 719.99, NOW()),
(2, 49.99, NOW()),
(3, 35.55, NOW()),
(4, 79.00, NOW()
);

-- Insert Sample Data into OrderItems table
INSERT INTO OrdersItems(OrderID, ProductID, Quantity, Price)
VALUES
(1,1,1,699.99),
(1,3,1,19.99),
(2,4,1,49.99),
(3,5,1,14.99),
(3,6,1,29.99);

-- Queries -------------------------------------------------------
-- 	Query 1 : Retrieve all orders for a specific customers

SELECT o.OrderID , o.OrderDate, o.TotalAmount, oi.ProductID, p.ProductName, oi.Quantity, oi.Price
FROM Orders o 
JOIN OrdersItems oi ON o.OrderID= oi.OrderID
JOIN Products p ON p.ProductID=oi.ProductID
WHERE o.CustomerID = 1;

-- Query 2: Find the total sales for each product
SELECT p.ProductID, p.ProductNAME, SUM(oi.Quantity * oi.Price) as TotalSales
FROM OrdersItems oi 
JOIN Products p
ON oi.ProductID=p.ProductID
GROUP BY p.ProductID, p.ProductName 
ORDER BY TotalSales DESC;

-- Query 3 : Calculate the Average of order value
SELECT AVG(TotalAmount) AS AverageOrderValue FROM Orders;

-- Query 4:  List the top 5 Customers by Total Spending
SELECT c.CustomerID, c.FirstName, c.LastName , SUM(o.TotalAmount) AS TotalSpending
FROM Customers c 
JOIN Orders o
ON o.CustomerID=c.CustomerID
GROUP BY c.CustomerID, c.FirstName, c.LastName
ORDER BY TotalSpending desc limit 5;

-- Query 5: Retrieve the most Popular Product
SELECT CategoryID, CategoryName, TotalQtySold, rn
FROM (
    SELECT 
        c.CategoryID,
        c.CategoryName,
        SUM(oi.Quantity) AS TotalQtySold,
        ROW_NUMBER() OVER (ORDER BY SUM(oi.Quantity) DESC) AS rn
    FROM OrdersItems oi
    JOIN Products p ON oi.ProductID = p.ProductID
    JOIN Category c ON c.CategoryID = p.CategoryID
    GROUP BY c.CategoryID, c.CategoryName
) sub
WHERE rn = 1;

-- insertion ---
INSERT INTO Products(ProductName, CategoryID, Price, Stock) 
VALUES
('Keyboard', 1, 39.99, 0);

-- Query 6: List all the Products that are out of Stock i.e. stock = 0
SELECT p.ProductID, p.ProductName, p.CategoryID, c.CategoryName, p.Price, p.Stock 
FROM Products p 
JOIN Category c
ON p.CategoryID=c.CategoryID
WHERE Stock = 0;

-- Query 7 : Find customers who placed orders in last 3O days
SELECT c.CustomerID, c.FirstName, c.LastName, c.Email, c.Phone
FROM Customers c
JOIN Orders o ON c.CustomerID = o.CustomerID
WHERE o.OrderDate >= DATE_SUB(NOW(), INTERVAL 30 DAY);

-- Query 8 : Calculate Total Number of Orders placed each month
SELECT 
      YEAR(o.OrderDate) as Year,
     MONTH(o.OrderDate) as Month, 
     COUNT(o.OrderID) as TotalOrders
FROM Orders o
JOIN OrdersItems oi
ON oi.OrderID=o.OrderID
GROUP BY MONTH(o.OrderDate), YEAR(o.OrderDate);

-- Query 9: Retrieve the details from the most recent order
SELECT o.OrderID, o.OrderDate,o.TotalAmount, c.FirstName, c.LastName
FROM Orders o 
JOIN Customers c
ON o.CustomerID=c.CustomerID
ORDER BY o.OrderDate DESC LIMIT 1;

-- Query 10: Find the average of Products in each Category
SELECT c.CategoryName, c.CategoryID, avg(p.Price) as AveragePrice
FROM Category c  
JOIN Products p
ON c.CategoryID = p.CategoryID
GROUP BY c.CategoryID , c.CategoryName;

-- Query 11: List Customers who haven't placed order
SELECT c.CustomerID, c.FirstName, c.LastName, c.Email, c.Phone, o.OrderID, o.TotalAmount
FROM Customers c RIGHT OUTER JOIN Orders o 
ON c.CustomerID=o.CustomerID
WHERE o.OrderID is NULL;

-- Query 12: Retrieve the Total Quantity sold for each product
SELECT (p.ProductID), p.ProductName, SUM(oi.Quantity) as TotalQty 
FROM Products p 
join OrdersItems oi
on p.ProductID=oi.ProductID
GROUP BY p.ProductID, p.ProductName;


-- Query 13: Calculate Total Revenue Generated from each Category

SELECT c.CategoryID,  c.CategoryName, SUM(oi.Quantity*oi.Price) as Revenue 
FROM Category c
JOIN Products p ON p.CategoryID=c.CategoryID
JOIN OrdersItems oi ON oi.ProductID=p.ProductID 
GROUP BY c.CategoryID,  c.CategoryName;

-- Query 14: Find the Highest priced product in each category

SELECT c.CategoryID,  c.CategoryName, p1.ProductID, p1.ProductName, p1.Price
FROM Category c JOIN Products p1
ON c.CategoryID=p1.CategoryID
WHERE p1.Price=(SELECT MAX(Price) FROM Products p2 where p2.CategoryID=p1.CategoryID)
ORDER BY p1.Price DESC;

-- Query 15: Retrieve Orders ith a Total amount greater than a specific value (e.g. $500)
SELECT oi.OrderID, oi.ProductID, p.ProductName, oi.Price
FROM OrdersItems oi
JOIN Products p
ON oi.ProductID=p.ProductID
WHERE oi.Price > 500;

-- Query 16: List Products  along with the numbwers of orders they appear in
SELECT p.ProductID, p.ProductName, COUNT(oi.OrderID) as OrderCount
FROM Products p
Join OrdersItems oi
ON p.ProductID=oi.ProductID
GROUP BY p.ProductID, p.ProductName
ORDER BY OrderCount DESC;

SHOW TABLES;
