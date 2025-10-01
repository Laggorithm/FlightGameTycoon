-- --------------------------------------------------------
-- Flight Game database schema
-- --------------------------------------------------------

-- Pudotetaan taulut turvallisessa järjestyksessä
DROP TABLE IF EXISTS flights;
DROP TABLE IF EXISTS contracts;
DROP TABLE IF EXISTS aircraft_upgrades;
DROP TABLE IF EXISTS base_upgrades;
DROP TABLE IF EXISTS available_bases; -- ei enää käytössä, varmuuden vuoksi drop
DROP TABLE IF EXISTS aircraft;
DROP TABLE IF EXISTS owned_bases;
DROP TABLE IF EXISTS aircraft_models;
DROP TABLE IF EXISTS random_events;
DROP TABLE IF EXISTS game_saves;

-- --------------------------------------------------------
-- 1. game_saves
-- --------------------------------------------------------
CREATE TABLE game_saves (
  save_id INT AUTO_INCREMENT PRIMARY KEY,
  player_name VARCHAR(40),
  current_day INT,
  cash DECIMAL(15,2),
  difficulty VARCHAR(40),
  status VARCHAR(40),
  rng_seed BIGINT,
  created_at DATETIME,
  updated_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 2. owned_bases (päivitetty rakenne)
-- --------------------------------------------------------
CREATE TABLE owned_bases (
  base_id INT AUTO_INCREMENT PRIMARY KEY,
  save_id INT NOT NULL,
  base_ident VARCHAR(40) NOT NULL,       -- viittaa airport.ident
  base_name VARCHAR(100) NOT NULL,
  acquired_day INT NOT NULL,
  purchase_cost DECIMAL(15,2) NOT NULL DEFAULT 0.00,
  sold_day INT NULL,                      -- varalla tulevaisuutta varten
  is_headquarters BOOLEAN DEFAULT FALSE,  -- varalla tulevaisuutta varten
  created_at DATETIME NOT NULL,
  updated_at DATETIME NOT NULL,
  CONSTRAINT fk_owned_bases_save FOREIGN KEY (save_id) REFERENCES game_saves(save_id),
  CONSTRAINT fk_owned_bases_airport FOREIGN KEY (base_ident) REFERENCES airport(ident),
  CONSTRAINT uq_base_per_save UNIQUE (save_id, base_ident)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 3. aircraft_models
-- --------------------------------------------------------
CREATE TABLE aircraft_models (
  model_code VARCHAR(40) PRIMARY KEY,
  manufacturer VARCHAR(40),
  model_name VARCHAR(40),
  purchase_price DECIMAL(15,2),
  base_cargo_kg DOUBLE,
  range_km DOUBLE,
  cruise_speed_kts DOUBLE,
  category VARCHAR(40), -- STARTER/SMALL/MEDIUM/LARGE/HUGE
  upkeep_price DECIMAL(15,2),
  efficiency_score DOUBLE,
  co2_kg_per_km DOUBLE,
  eco_class VARCHAR(40),
  eco_fee_multiplier DOUBLE
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 4. aircraft
-- --------------------------------------------------------
CREATE TABLE aircraft (
  aircraft_id INT AUTO_INCREMENT PRIMARY KEY,
  model_code VARCHAR(40),
  base_level INT,
  current_airport_ident VARCHAR(40),
  registration VARCHAR(40),
  nickname VARCHAR(40),
  acquired_day INT,
  purchase_price DECIMAL(15,2),
  condition_percent INT,
  status VARCHAR(40),
  hours_flown INT,
  sold_day INT,
  sale_price DECIMAL(15,2),
  speed_kph DOUBLE,
  save_id INT,
  base_id INT,
  FOREIGN KEY (model_code) REFERENCES aircraft_models(model_code),
  FOREIGN KEY (base_id) REFERENCES owned_bases(base_id),
  FOREIGN KEY (current_airport_ident) REFERENCES airport(ident),
  FOREIGN KEY (save_id) REFERENCES game_saves(save_id)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 5. random_events
-- --------------------------------------------------------
CREATE TABLE random_events (
  event_id INT AUTO_INCREMENT PRIMARY KEY,
  event_name VARCHAR(100) NOT NULL,
  category ENUM('GOOD','BAD','CATASTROPHIC') NOT NULL,
  description TEXT,
  probability DECIMAL(5,4), -- esim. 0.2500 = 25%
  effect TEXT,
  duration_days INT,
  sound_file VARCHAR(255),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 6. contracts
-- --------------------------------------------------------
CREATE TABLE contracts (
  contractId INT AUTO_INCREMENT PRIMARY KEY,
  payload_kg DOUBLE,
  reward DECIMAL(15,2),
  penalty DECIMAL(15,2),
  priority VARCHAR(40),
  created_day INT,
  deadline_day INT,
  accepted_day INT,
  completed_day INT,
  status VARCHAR(40),
  lost_packages INT,
  damaged_packages INT,
  save_id INT,
  aircraft_id INT,
  ident VARCHAR(40),
  event_id INT,
  FOREIGN KEY (save_id) REFERENCES game_saves(save_id),
  FOREIGN KEY (aircraft_id) REFERENCES aircraft(aircraft_id),
  FOREIGN KEY (ident) REFERENCES airport(ident),
  FOREIGN KEY (event_id) REFERENCES random_events(event_id)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 7. flights
-- --------------------------------------------------------
CREATE TABLE flights (
  flight_id INT AUTO_INCREMENT PRIMARY KEY,
  created_day INT,
  dep_day INT,
  arrival_day INT,
  status VARCHAR(40),
  distance_km DOUBLE,
  schedule_delay_min INT,
  emission_kg_co2 DOUBLE,
  eco_fee DECIMAL(15,2),
  dep_ident VARCHAR(40),
  arr_ident VARCHAR(40),
  aircraft_id INT,
  save_id INT,
  contract_id INT,
  FOREIGN KEY (dep_ident) REFERENCES airport(ident),
  FOREIGN KEY (arr_ident) REFERENCES airport(ident),
  FOREIGN KEY (aircraft_id) REFERENCES aircraft(aircraft_id),
  FOREIGN KEY (save_id) REFERENCES game_saves(save_id),
  FOREIGN KEY (contract_id) REFERENCES contracts(contractId)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 8. aircraft_upgrades
-- --------------------------------------------------------
CREATE TABLE aircraft_upgrades (
  aircraft_upgrade_id INT AUTO_INCREMENT PRIMARY KEY,
  aircraft_id INT,
  upgrade_code VARCHAR(40),
  level INT,
  installed_day INT,
  FOREIGN KEY (aircraft_id) REFERENCES aircraft(aircraft_id)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 9. base_upgrades (progress-historia SMALL/MEDIUM/LARGE/HUGE)
-- --------------------------------------------------------
CREATE TABLE base_upgrades (
  base_upgrade_id INT AUTO_INCREMENT PRIMARY KEY,
  base_id INT,
  upgrade_code VARCHAR(40),
  installed_day INT,
  upgrade_cost DECIMAL(15,2),
  FOREIGN KEY (base_id) REFERENCES owned_bases(base_id),
  INDEX idx_base_upgrades_base_day (base_id, installed_day),
  INDEX idx_base_upgrades_code (upgrade_code)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- Random events (esimerkkidata)
-- --------------------------------------------------------
INSERT INTO random_events (event_name, category, description, probability, effect, duration_days, sound_file)
VALUES
('Volcano', 'BAD', 'Have to wait 1–7 days (random)', 0.0500, 'Delay random 1–7 days', 7, 'sounds/volcano.mp3'),
('Aliens', 'BAD', 'Chance aliens take interest in your goods', 0.0010, 'Lose 10% of packages for 3 days or lose 1 worker/day', 3, 'sounds/aliens.mp3'),
('Freezing Cold', 'BAD', 'Wings freeze before or during flight', 0.2000, 'Require fee/unfreeze mid-flight, up to 20% crash chance', 2, 'sounds/freezing.mp3'),
('Storm Clouds', 'BAD', 'Packages damaged, possible lightning hit', 0.2500, 'Lose % reward, 1% crash chance, 20% repair needed', 1, 'sounds/storm.mp3'),
('Hurricane', 'BAD', 'Severe turbulence', 0.1000, '40% crash chance and damage packages', 1, 'sounds/hurricane.mp3'),
('Meteor', 'CATASTROPHIC', 'Meteor strike destroys plane', 0.0100, 'Instant plane loss', 0, 'sounds/meteor.mp3'),
('Worker Strikes', 'BAD', 'Workers go on strike', 0.0500, 'Wait 1–3 days (random)', 3, 'sounds/strike.mp3'),
('Perfect Day', 'GOOD', 'Clear skies, optimal conditions', 0.0500, '0.5x travel time', 1, 'sounds/perfect_day.mp3'),
('Sunny Sky', 'GOOD', 'Mild weather boost', 0.0800, '0.8x travel time', 1, 'sounds/sunny.mp3'),
('Favorable Winds', 'GOOD', 'Strong tailwind', 0.0700, '0.7x travel time', 1, 'sounds/wind.mp3'),
('Mile High Club', 'GOOD', 'Crew distracted mid-flight', 0.0200, 'Random: -1 day, +1 day, or plane crash (33/33/33)', 1, 'sounds/milehigh.mp3');

-- --------------------------------------------------------
-- Starter Aircraft (ei listata kaupassa; vain uuden pelin lahja)
-- --------------------------------------------------------
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('DC3FREE', 'Douglas', 'DC-3 Starter', 0, 2000,
 800, 150, 'STARTER', 1000, 0.40,
 0.20, 'E', -0.05);

-- --------------------------------------------------------
-- Small Aircraft
-- --------------------------------------------------------
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('C172', 'Cessna', '172 Skyhawk', 300000, 300,
 1285, 122, 'SMALL', 5000, 0.65,
 0.12, 'D', -0.10),

('PC12', 'Pilatus', 'PC-12 NGX', 4900000, 1000,
 3340, 280, 'SMALL', 20000, 0.72,
 0.18, 'C', -0.15),

('BE58', 'Beechcraft', 'Baron 58', 1200000, 600,
 1480, 200, 'SMALL', 8000, 0.68,
 0.15, 'C', -0.12),

('KODI', 'Daher', 'Kodiak 100', 2200000, 1400,
 1900, 183, 'SMALL', 12000, 0.70,
 0.16, 'C', -0.14);

-- Lisättyjä SMALL-malleja
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('C208B', 'Cessna', '208B Grand Caravan EX', 2300000, 1400,
 1850, 186, 'SMALL', 11000, 0.71,
 0.17, 'C', -0.14),

('PC6', 'Pilatus', 'PC-6 Porter', 1000000, 900,
 1200, 125, 'SMALL', 7000, 0.66,
 0.14, 'C', -0.12),

('BN2', 'Britten-Norman', 'BN-2 Islander', 1200000, 1000,
 1400, 140, 'SMALL', 9000, 0.67,
 0.16, 'C', -0.13);

-- --------------------------------------------------------
-- Medium Aircraft
-- --------------------------------------------------------
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('AT72F', 'ATR', '72-600F', 26000000, 8900,
 1528, 275, 'MEDIUM', 80000, 0.78,
 0.35, 'B', -0.30),

('B733F', 'Boeing', '737-300F', 35000000, 18700,
 2950, 420, 'MEDIUM', 120000, 0.74,
 0.55, 'C', -0.35),

('DC9F', 'McDonnell Douglas', 'DC-9F', 24000000, 18000,
 2000, 400, 'MEDIUM', 95000, 0.73,
 0.45, 'C', -0.28),

('E190F', 'Embraer', 'E190 Freighter', 27000000, 13500,
 3300, 450, 'MEDIUM', 100000, 0.75,
 0.40, 'B', -0.25);

-- Lisättyjä MEDIUM-malleja
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('AT42F', 'ATR', '42-500F', 20000000, 5400,
 1550, 250, 'MEDIUM', 60000, 0.80,
 0.32, 'B', -0.28),

('DH8Q4F', 'De Havilland', 'Dash 8 Q400PF', 27000000, 9000,
 2000, 360, 'MEDIUM', 85000, 0.77,
 0.36, 'B', -0.30),

('A321F', 'Airbus', 'A321-200P2F', 48000000, 27000,
 3700, 450, 'MEDIUM', 140000, 0.76,
 0.52, 'C', -0.32),

('B752F', 'Boeing', '757-200F', 55000000, 32000,
 5800, 450, 'MEDIUM', 160000, 0.72,
 0.60, 'D', -0.34);

-- --------------------------------------------------------
-- Large Aircraft
-- --------------------------------------------------------
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('B744F', 'Boeing', '747-400F', 125000000, 113000,
 8230, 490, 'LARGE', 500000, 0.70,
 1.20, 'E', -0.60),

('A332F', 'Airbus', 'A330-200F', 110000000, 70000,
 7400, 470, 'LARGE', 400000, 0.76,
 1.00, 'D', -0.50),

('DC10F', 'McDonnell Douglas', 'DC-10F', 80000000, 66000,
 6100, 480, 'LARGE', 300000, 0.68,
 1.10, 'E', -0.55),

('MD11F', 'McDonnell Douglas', 'MD-11F', 90000000, 91000,
 6750, 485, 'LARGE', 350000, 0.72,
 1.00, 'D', -0.52);

-- Lisättyjä LARGE-malleja
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('A306F', 'Airbus', 'A300-600F', 65000000, 48000,
 4400, 460, 'LARGE', 250000, 0.69,
 0.95, 'D', -0.45),

('B763F', 'Boeing', '767-300F', 95000000, 58000,
 6000, 470, 'LARGE', 300000, 0.74,
 0.98, 'D', -0.48),

('B77LF', 'Boeing', '777F', 150000000, 102000,
 9070, 490, 'LARGE', 520000, 0.75,
 1.15, 'D', -0.58);

-- --------------------------------------------------------
-- Huge Aircraft
-- --------------------------------------------------------
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('AN225', 'Antonov', 'An-225 Mriya', 250000000, 250000,
 15400, 460, 'HUGE', 1000000, 0.60,
 2.50, 'F', -1.00),

('A388F', 'Airbus', 'A380-800F (concept)', 230000000, 150000,
 15200, 490, 'HUGE', 850000, 0.65,
 2.00, 'F', -0.90),

('C5GALX', 'Lockheed', 'C-5 Galaxy', 210000000, 127000,
 12200, 465, 'HUGE', 900000, 0.62,
 2.20, 'F', -0.95);

-- Lisättyjä HUGE-malleja
INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
)
VALUES
('AN124', 'Antonov', 'An-124 Ruslan', 180000000, 120000,
 4800, 430, 'HUGE', 800000, 0.61,
 2.20, 'F', -0.92),

('B748F', 'Boeing', '747-8F', 170000000, 137000,
 8130, 493, 'HUGE', 600000, 0.74,
 1.25, 'D', -0.62);