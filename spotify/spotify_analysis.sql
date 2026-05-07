-- create table
DROP TABLE IF EXISTS spotify;
CREATE TABLE spotify (
    artist VARCHAR(255),
    track VARCHAR(255),
    album VARCHAR(255),
    album_type VARCHAR(50),
    danceability FLOAT,
    energy FLOAT,
    loudness FLOAT,
    speechiness FLOAT,
    acousticness FLOAT,
    instrumentalness FLOAT,
    liveness FLOAT,
    valence FLOAT,
    tempo FLOAT,
    duration_min FLOAT,
    title VARCHAR(255),
    channel VARCHAR(255),
    views FLOAT,
    likes FLOAT,
    comments FLOAT,
    licensed BOOLEAN,
    official_video BOOLEAN,
    stream BIGINT,
    energy_liveness FLOAT,
    most_played_on VARCHAR(50)
);
--------EDA----------------------
SELECT COUNT(*) FROM spotify;

SELECT COUNT(DISTINCT artist) FROM spotify;

SELECT COUNT(DISTINCT album) FROM spotify;

SELECT DISTINCT album_type FROM spotify;

SELECT MAX(duration_min) fROM spotify;

SELECT MIN(duration_min) fROM spotify;--No way a song can have 0 duration, check 

--We see there are 2 songs with 0 durations, let's delete these rows
SELECT * FROM spotify
WHERE duration_min=0;

DELETE FROM spotify
WHERE duration_min=0;

SELECT * FROM spotify
WHERE duration_min=0

SELECT DISTINCT channel FROM spotify;

SELECT DISTINCT most_played_on FROM spotify;

/*------------------------------------------------
--Data Analysis
--------------------------------------------------
Retrieve the names of all tracks that have more than 1 billion streams.
List all albums along with their respective artists.
Get the total number of comments for tracks where licensed = TRUE.
Find all tracks that belong to the album type single.
Count the total number of tracks by each artist.
*/

--Retrieve the names of all tracks that have more than 1 billion streams.

SELECT track FROM spotify
where stream>1000000000;

--List all albums along with their respective artists.

SELECT (album), artist FROM spotify;
SELECT DISTINCT(album), artist FROM spotify;

--Get the total number of comments for tracks where licensed = TRUE.

SELECT SUM(comments)AS total_comments FROM spotify
WHERE licensed = TRUE;


--Find all tracks that belong to the album type single.

SELECT track from spotify
where album_type='single';

--Count the total number of tracks by each artist.

Select artist , count(track)as total_tracks from spotify
group by artist
ORDER BY 2 ASC;

/*----------------------------------------------------------------------
Calculate the average danceability of tracks in each album.
Find the top 5 tracks with the highest energy values.
List all tracks along with their views and likes where official_video = TRUE.
For each album, calculate the total views of all associated tracks.
Retrieve the track names that have been streamed on Spotify more than YouTube.
----------------------------------------------------------------------------*/

--Calculate the average danceability of tracks in each album.
SELECT album, 
       avg(danceability) as avg_danceability
FROM spotify
GROUP BY album
ORDER BY avg_danceability DESC;

--Find the top 5 tracks with the highest energy values.
SELECT DISTINCT track, 
 MAX(energy) 
 from spotify
group by track
order by MAX(energy) desc 
limit 5;

--List all tracks along with their views and likes where official_video = TRUE.

SELECT track, 
       SUM(views) as total_views, 
	   SUM(likes) as total_likes
FROM spotify
WHERE official_video = 'true'
GROUP BY track
ORDER BY total_views DESC
limit 5;

--For each album, calculate the total views of all associated tracks.

SELECT album,track, SUM(views) as total_views
from spotify
group by album, track
order by total_views desc;

--Retrieve the track names that have been streamed on Spotify more than YouTube.
SELECT * FROM
(SELECT track , --most_played_on, 
COALESCE(SUM(CASE WHEN most_played_on='Youtube' THEN stream END),0) as streamed_on_youtube,
COALESCE(SUM(CASE WHEN most_played_on='Spotify' THEN stream END),0) as streamed_on_spotify
from spotify
Group by track
) AS t1
where streamed_on_spotify > streamed_on_youtube
and streamed_on_youtube<>0;

/*-----------------------------------------------------------------------
Find the top 3 most-viewed tracks for each artist using window functions.
Write a query to find tracks where the liveness score is above the average.
Use a WITH clause to calculate the difference between the highest and lowest energy values for tracks in each album.
*/

--Find the top 3 most-viewed tracks for each artist using window functions.
WITH ranking_artist 
AS (SELECT artist,
       track,
	   SUM(views) as total_view,
	   DENSE_RANK() OVER(PARTITION BY artist ORDER BY SUM(views) DESC) as rank
FROM spotify
GROUP BY artist,track
ORDER BY artist, total_view DESC)

SELECT * FROM ranking_artist
where rank<=3

--Write a query to find tracks where the liveness score is above the average.
SELECT * FROM spotify 
Where liveness>(SELECT AVG(liveness) FROM spotify);

--Use a WITH clause to calculate the difference between 
--the highest and lowest energy values for tracks in each album.
WITH cte AS
(SELECT album,
       MAX(energy) as max_energy , 
	   MIN(energy) as min_energy 
from spotify
group by 1)
SELECT album, (max_energy-min_energy) as difference
FROM cte
ORDER BY difference;

	   