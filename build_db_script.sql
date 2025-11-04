-- --------------------------------------------------------
-- Flight Game database schema
-- --------------------------------------------------------

-- Pudotetaan taulut turvallisessa järjestyksessä (riippuvuudet huomioiden)
DROP TABLE IF EXISTS market_aircraft;
DROP TABLE IF EXISTS flights;
DROP TABLE IF EXISTS contracts;
DROP TABLE IF EXISTS aircraft_upgrades;
DROP TABLE IF EXISTS base_upgrades;
DROP TABLE IF EXISTS available_bases; -- ei enää käytössä, varmuuden vuoksi drop
DROP TABLE IF EXISTS aircraft;
DROP TABLE IF EXISTS owned_bases;
DROP TABLE IF EXISTS save_event_log;
DROP TABLE IF EXISTS player_fate;
DROP TABLE IF EXISTS random_events;
DROP TABLE IF EXISTS aircraft_models;
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
  description TEXT,
  chance_max INT,
  package_multiplier DOUBLE,
  plane_damage INT,
  days DOUBLE,
  duration INT,
  sound_file VARCHAR(255)
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
  final_reward DECIMAL(15,2),
  event_adjustment DECIMAL(15,2),
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
-- 6b. save_event_log (tallennuksen tapahtumahistoria)
-- --------------------------------------------------------
CREATE TABLE save_event_log (
  log_id INT AUTO_INCREMENT PRIMARY KEY,
  save_id INT NOT NULL,
  event_day INT NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  payload TEXT,
  created_at DATETIME NOT NULL,
  FOREIGN KEY (save_id) REFERENCES game_saves(save_id),
  INDEX idx_event_log_save_day (save_id, event_day),
  INDEX idx_event_log_type (event_type)
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
  FOREIGN KEY (aircraft_id) REFERENCES aircraft(aircraft_id),
  INDEX idx_air_upg_air_code (aircraft_id, upgrade_code),
  INDEX idx_air_upg_day (installed_day)
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
CREATE TABLE player_fate (
  seed INT NOT NULL,
  day INT NOT NULL,
  event_name VARCHAR(100) NOT NULL,
  PRIMARY KEY (seed, day),
  INDEX idx_player_fate_seed (seed)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- 10. market_aircraft (Käytettyjen koneiden kauppapaikka)
-- --------------------------------------------------------
CREATE TABLE market_aircraft (
  market_id INT AUTO_INCREMENT PRIMARY KEY,
  model_code VARCHAR(40) NOT NULL,
  purchase_price DECIMAL(15,2) NOT NULL,
  condition_percent INT NOT NULL,
  hours_flown INT NOT NULL,
  manufactured_day INT NOT NULL,
  market_notes TEXT NULL,
  listed_day INT NOT NULL,
  FOREIGN KEY (model_code) REFERENCES aircraft_models(model_code)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;

-- --------------------------------------------------------
-- Random events
-- --------------------------------------------------------
INSERT INTO random_events (
  event_name,
  description,
  chance_max,
  package_multiplier,
  plane_damage,
  days,
  duration,
  sound_file
) VALUES
('Volcano', NULL, 50, 0.53, 40, 3.0, 1, 'sfx/volcano-eruption.mp3'),
('Aliens', NULL, 100, 0.9, 10, 0.0, 7, 'sfx/the-x-files-theme.mp3'),
('Freezing Cold', NULL, 10, 0.8, 7, 1.0, 2, 'sfx/frostpunk-generator-sound.mp3'),
('Storm Clouds', NULL, 5, 0.7, 15, 1.0, 3, 'sfx/thunder-sound-effect.mp3'),
('Hurricane', NULL, 15, 0.6, 25, 2.0, 1, 'sfx/49_20siren.mp3'),
('Meteor', NULL, 70, 0.0, 100, 0.0, 1, 'sfx/impact_explosion_03.mp3'),
('Workers Strike', NULL, 6, 0.5, 0, 2.0, 3, 'sfx/screaming-protester.mp3'),
('Sunny Sky', NULL, 3, 1.0, 0, 0.8, 1, 'sfx/here-comes-the-sun.mp3'),
('Favorable Winds', NULL, 7, 1.0, 0, 0.7, 2, 'sfx/yoshis-island-music-map-theme-short.mp3'),
('Best Day Ever', NULL, 15, 1.5, 0, 0.5, 1, 'sfx/life_could_be_a_dream.mp3'),
('Normal Day', NULL, 1, 1.0, 0, 1.0, 1, NULL);

-- --------------------------------------------------------
-- Lentokonemallit - Vähän koitettu balansoida
-- --------------------------------------------------------

INSERT INTO aircraft_models (
  model_code, manufacturer, model_name, purchase_price, base_cargo_kg,
  range_km, cruise_speed_kts, category, upkeep_price, efficiency_score,
  co2_kg_per_km, eco_class, eco_fee_multiplier
) VALUES
-- Starter Aircraft
('DC3FREE', 'Douglas', 'DC-3 Starter', 0, 2000, 800, 150, 'STARTER', 1000, 0.40, 0.20, 'E', 0.85),

-- Small Aircraft
('C172', 'Cessna', '172 Skyhawk', 120000, 300, 1285, 122, 'SMALL', 3000, 0.65, 0.12, 'D', 0.90),
('PC6', 'Pilatus', 'PC-6 Porter', 400000, 900, 1200, 125, 'SMALL', 6000, 0.66, 0.14, 'C', 0.92),
('BE58', 'Beechcraft', 'Baron 58', 550000, 600, 1480, 200, 'SMALL', 7000, 0.68, 0.15, 'C', 0.88),
('BN2', 'Britten-Norman', 'BN-2 Islander', 600000, 1000, 1400, 140, 'SMALL', 8000, 0.67, 0.16, 'C', 0.87),
('KODI', 'Daher', 'Kodiak 100', 900000, 1400, 1900, 183, 'SMALL', 12000, 0.70, 0.16, 'C', 0.86),
('C208B', 'Cessna', '208B Grand Caravan EX', 1100000, 1400, 1850, 186, 'SMALL', 11000, 0.71, 0.17, 'C', 0.86),
('PC12', 'Pilatus', 'PC-12 NGX', 1800000, 1000, 3340, 280, 'SMALL', 20000, 0.72, 0.18, 'C', 0.85),

-- Medium Aircraft
('AT42F', 'ATR', '42-500F', 3500000, 5400, 1550, 250, 'MEDIUM', 30000, 0.80, 0.32, 'B', 0.80),
('DC9F', 'McDonnell Douglas', 'DC-9F', 4200000, 18000, 2000, 400, 'MEDIUM', 45000, 0.73, 0.45, 'C', 0.78),
('AT72F', 'ATR', '72-600F', 5000000, 8900, 1528, 275, 'MEDIUM', 40000, 0.78, 0.35, 'B', 0.75),
('E190F', 'Embraer', 'E190 Freighter', 5500000, 13500, 3300, 450, 'MEDIUM', 50000, 0.75, 0.40, 'B', 0.76),
('DH8Q4F', 'De Havilland', 'Dash 8 Q400PF', 6000000, 9000, 2000, 360, 'MEDIUM', 42000, 0.77, 0.36, 'B', 0.75),
('B733F', 'Boeing', '737-300F', 7500000, 18700, 2950, 420, 'MEDIUM', 60000, 0.74, 0.55, 'C', 0.70),
('A321F', 'Airbus', 'A321-200P2F', 9000000, 27000, 3700, 450, 'MEDIUM', 70000, 0.76, 0.52, 'C', 0.72),
('B752F', 'Boeing', '757-200F', 11000000, 32000, 5800, 450, 'MEDIUM', 80000, 0.72, 0.60, 'D', 0.68),

-- Large Aircraft
('A306F', 'Airbus', 'A300-600F', 15000000, 48000, 4400, 460, 'LARGE', 125000, 0.69, 0.95, 'D', 0.65),
('DC10F', 'McDonnell Douglas', 'DC-10F', 18000000, 66000, 6100, 480, 'LARGE', 150000, 0.68, 1.10, 'E', 0.60),
('MD11F', 'McDonnell Douglas', 'MD-11F', 22000000, 91000, 6750, 485, 'LARGE', 175000, 0.72, 1.00, 'D', 0.62),
('B763F', 'Boeing', '767-300F', 25000000, 58000, 6000, 470, 'LARGE', 150000, 0.74, 0.98, 'D', 0.64),
('A332F', 'Airbus', 'A330-200F', 28000000, 70000, 7400, 470, 'LARGE', 200000, 0.76, 1.00, 'D', 0.65),
('B744F', 'Boeing', '747-400F', 35000000, 113000, 8230, 490, 'LARGE', 250000, 0.70, 1.20, 'E', 0.55),
('B77LF', 'Boeing', '777F', 40000000, 102000, 9070, 490, 'LARGE', 260000, 0.75, 1.15, 'D', 0.58),

-- Huge Aircraft
('B748F', 'Boeing', '747-8F', 50000000, 137000, 8130, 493, 'HUGE', 300000, 0.74, 1.25, 'D', 0.62),
('AN124', 'Antonov', 'An-124 Ruslan', 60000000, 120000, 4800, 430, 'HUGE', 400000, 0.61, 2.20, 'F', 0.55),
('C5GALX', 'Lockheed', 'C-5 Galaxy', 75000000, 127000, 12200, 465, 'HUGE', 450000, 0.62, 2.20, 'F', 0.52),
('A388F', 'Airbus', 'A380-800F (concept)', 90000000, 150000, 15200, 490, 'HUGE', 425000, 0.65, 2.00, 'F', 0.58),
('AN225', 'Antonov', 'An-225 Mriya', 120000000, 250000, 15400, 460, 'HUGE', 500000, 0.60, 2.50, 'F', 0.50);