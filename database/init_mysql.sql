CREATE DATABASE IF NOT EXISTS `lite_erp`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

CREATE USER IF NOT EXISTS 'lite_erp'@'localhost' IDENTIFIED BY 'LiteErp@2026!';
CREATE USER IF NOT EXISTS 'lite_erp'@'127.0.0.1' IDENTIFIED BY 'LiteErp@2026!';
ALTER USER 'lite_erp'@'localhost' IDENTIFIED BY 'LiteErp@2026!';
ALTER USER 'lite_erp'@'127.0.0.1' IDENTIFIED BY 'LiteErp@2026!';
GRANT ALL PRIVILEGES ON `lite_erp`.* TO 'lite_erp'@'localhost';
GRANT ALL PRIVILEGES ON `lite_erp`.* TO 'lite_erp'@'127.0.0.1';
FLUSH PRIVILEGES;
