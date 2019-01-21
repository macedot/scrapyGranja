import scrapy
import re
import os
from scrapy.loader import ItemLoader
from granjaRaces.items import GranjaRacesItem

"""
# TRIVIA 1 2017-03-xx:
#	At Jan 2017, the asfalt of KGV race track was completly rebuild.
#	Thus all previous race and lap data is 'useless' for actual predictions.
#	The folloing ID refers to the first race at KGV after race track rebuild.
#		MIN_RACE_ID = 36612
# TRIVIA 2 2017-03-13:
#	Seems that Granja is running different track layouts/configuration
#	using the same 'CIRCUITO XX' identifier. Since the physical track layout 
#	have changed a lot, some new layout possibilities will be possible,
#	and 'CIRCUITO xx' definitions will be reset. We need to monitor their data
#	and estabilish this a new MIN_RACE_ID when this reset occurs.

Result list URL:
	http://www.kgv.net.br/resultados/Default.aspx

Example of url at resulting page:
	http://www.kgv.net.br/resultados/Results.aspx?UserId=&way=../Arquivos/KGV-G-20190117001238969-Rental-Resultado.html&year=2019&month=Janeiro&day=Todos

Example DIRECT ACCESS result page:
	http://www.kgv.net.br/Arquivos/KGV-G-20190117001238969-Rental-Resultado.html
	-> Granja viana + Standard rental kart
	
	http://www.kgv.net.br/Arquivos/KGV-G-20190116232555125-Interlagos-Resultado.html
	-> Interlagos + Standard rental kart

First Race in 2019
	http://www.kgv.net.br/Arquivos/KGV-G-20190103174040999-Rental-Resultado.html

"""

# first race of 2019
MIN_RACE_ID = 20190103174040999

# Usable columns only
DICT_HEADER = {
	u'POS' : 'racePosition',
	u'NO.' : 'kartNumber',
	u'NOME' : 'driverName',
	u'CLASSE' : 'driverClass',		# RENTAL
	u'VOLTAS' : 'numOfLaps',
	u'TOTAL TEMPO' : 'raceTime',
	u'MELHOR TEMPO' : 'bestLapTime'
}

class GranjaRaceSpider(scrapy.Spider):
	name = 'granjaRaces'

	def start_requests(self):
		return [scrapy.Request('http://www.kgv.net.br/resultados/Default.aspx', callback = self.result_list)]

	def result_list(self, response):
		# $> scrapy crawl granjaRaces -a begin=36620 -a end=36642
		
		"""
		http://www.kgv.net.br/resultados/Results.aspx?UserId=&way=../Arquivos/KGV-G-20190117001238969-Rental-Resultado.html&year=2019&month=Janeiro&day=Todos

		http://www.kgv.net.br/resultados/Results.aspx
			?UserId=
			&way=../Arquivos/KGV-G-20190117001238969-Rental-Resultado.html
			&year=2019
			&month=Janeiro
			&day=Todos
		""" 
		
		# get the list of available race results for current result page (default: current month)
		raceIdList_raw = response.css('a').re(r'Results\.aspx\?.+\&amp;way=\.\.\/Arquivos\/KGV-G-(.+)-Rental-Resultado\.html')
		self.logger.debug('RAW raceIdList -> ' + ','.join(raceIdList_raw))

		firstRaceId = int(getattr(self, 'begin', -1))
		if firstRaceId < MIN_RACE_ID:
			firstRaceId = MIN_RACE_ID
		
		lastRaceId = int(getattr(self, 'end', -1))
		if lastRaceId < 0:
			lastRaceId = int(max(raceIdList_raw))

		if lastRaceId < firstRaceId:
			lastRaceId = firstRaceId

		self.logger.info('Scrapping races from %i to %i', firstRaceId, lastRaceId)

		# yelds scrap requests
		raceIdList = list(map(int, raceIdList_raw))
		raceIdList = [i for i in raceIdList if i >= firstRaceId and i <= lastRaceId]
		for raceId in raceIdList:
			# url = '%s?tipo=%i&id=%i' % (RESULT_URL, RESULT_TYPE, raceId)
			url = 'http://www.kgv.net.br/Arquivos/KGV-G-%d-Rental-Resultado.html' % (raceId)
			self.logger.debug('yielding a start url: %s' % url)
			yield scrapy.Request(url, callback=self.parse)

	def parse(self, response):
		# http://www.kgv.net.br/Arquivos/KGV-G-20190103174040999-Rental-Resultado.html
		self.logger.debug('response.url = [' + response.url + ']')

		try:
			raceId = re.search(r'Arquivos\/KGV-G-(.+)-Rental-Resultado\.html', response.url).group(1)
		except AttributeError:
			self.logger.error('Invalid URL: ' + response.url)
			return

		# filter body only with 'GRANJA VIANA'
		if 'GRANJA VIANA' not in response.text:
			self.logger.warning('Skipping RACE (Not GRANJA VIANA): ' + raceId)
			return

		# discart INTERLAGOS races (for now...)
		if 'INTERLAGOS' in response.text:
			self.logger.warning('Skipping RACE (INTERLAGOS): ' + raceId)
			return

		# filter body only with 'GRANJA VIANA'
		if 'RENTAL' not in response.text:
			self.logger.warning('Skipping RACE (Not RENTAL): ' + raceId)
			return
			
		self.logger.info('Scrapping RACE: %s' % raceId)
		self.persistToFile(raceId, response)

		# get track configuration
		# KARTODROMO INTERNACIONAL GRANJA VIANA KGV RACE TRACKS - CIRCUITO 01
		headerbig = response.css('div.headerbig::text').extract_first()
		if headerbig is None:
			self.logger.error('Missing headerbig (%s)' % raceId)
			return
		
		if '-' not in headerbig:
			self.logger.error('INVALID HEADER (Missing separator): %s' % headerbig)
			return

		self.logger.debug('headerbig = "%s"' % headerbig)

		trackConfig = headerbig.split('-')[1].strip()
		self.logger.debug('trackConfig = "%s"' % trackConfig)

		# get table header
		listHeader = [h.strip().upper() for h in response.css('th.column::text').extract()]
		if not listHeader:
			self.logger.error('No table header for RACE %s' % raceId)
			return

		# check header
		for h in DICT_HEADER.keys():
			if h not in listHeader:
				self.logger.error('MISSING HEADER COLUMN (%s): %s' % (raceId, h))
				return

		# get table data
		tableData = response.xpath('//table/tr')[1:]
		for line in tableData:
			raceEntryData = {}
			i = 1
			for h in listHeader:
				if h in DICT_HEADER.keys():
					key = DICT_HEADER[h]
					value = line.xpath('td[%i]/text()' % i).extract_first()
					raceEntryData[key] = value
				i += 1
		
			raceLoader = ItemLoader(item=GranjaRacesItem(), response=response)
			raceLoader.add_value('raceId', raceId)
			raceLoader.add_value('trackConfig', trackConfig)
			for col in raceEntryData.keys():
				raceLoader.add_value(col, raceEntryData[col])

			if not raceEntryData['racePosition'].isdigit():
				raceEntryData['racePosition'] = 99
			raceLoader.add_value('id', int(raceEntryData['racePosition']) + 100 * int(raceId))

			yield raceLoader.load_item()

	def persistToFile(self, raceId, response):
		filename = 'raceResults/%s.html' % raceId
		with open(filename, 'wb') as file:
			file.write(response.body)
		self.log('RACE %s saved file %s' % (raceId, filename))
