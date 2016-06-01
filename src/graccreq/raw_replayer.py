import pika
import json
import sys
import logging
from elasticsearch import Elasticsearch
from elasticsearch_dsl import Search
import traceback

def RawReplayerFactory(msg, parameters):
    # Create the raw replayer class
    #print "Creating raw replayer"
    try:
        replayer = RawReplayer(msg, parameters)
        replayer.run()
    except Exception, e:
        logging.error(traceback.format_exc())


class RawReplayer:
    def __init__(self, message, parameters):
        self.msg = message
        self.parameters = parameters
        self.control = False
        if 'control' in self.msg and self.msg['control']:
            self.control = True
            self.control_exchange = self.msg['control']
            self.control_key = self.msg['control-key']
        
    def run(self):
        logging.debug("Beggining run of RawReplayer")
        self._conn = pika.adapters.blocking_connection.BlockingConnection(self.parameters)
        self._chan = self._conn.channel()
        self._chan.add_on_return_callback(self.on_return)
        
        # Send start message to control channel, if requested
        self._sendControlMessage({'status': 'ok', 'stage': 'starting'})
        
        # Return the results
        toReturn = {}
        toReturn['status'] = 'ok'

        # Query elsaticsearch
        logging.info("Sending response to %s with routing key %s" % (self.msg['destination'], self.msg['routing_key']))
        try:
            
            for record in self._queryElasticsearch(self.msg['from'], self.msg['to'], None):
                try:
                    self._chan.basic_publish(self.msg['destination'], self.msg['routing_key'], json.dumps(toReturn),
                                             pika.BasicProperties(content_type='text/json',
                                             delivery_mode=1))
                except Exception, e:
                    logging.error("Exception caught in basic_publish: %s" % str(e))
                    raise e
        
        except Exception, e:
            logging.error("Exception caught in query ES: %s" % str(e))
            
        
        self.sendControlMessage({'status': 'ok', 'stage': 'finished'})
        
        self._conn.close()
        
        return
        
    def on_return(self, channel, method, properties, body):
        sys.stderr.write("Got returned message\n")
        
    def _queryElasticsearch(self, from_date, to_date, query):
        logging.debug("Connecting to ES")
        client = Elasticsearch()
        
        logging.debug("Beginning search")
        s = Search(using=client, index='gracc-osg-*')
        s = s.filter('range', **{'@timestamp': {'from': from_date, 'to': to_date }})
        
        logging.debug("About to execute query:\n%s" % str(s.to_dict()))
        
        for hit in s.scan():
            yield hit
        
    def _sendControlMessage(self, control_msg):
        
        if not self.control:
            return
        
        try:
            logging.debug("Sending start command to control exchange %s" % self.control_exchange)
            self._chan.basic_publish(self.control_exchange, self.control_key, json.dumps(control_msg),
                                 pika.BasicProperties(content_type='text/json',
                                           delivery_mode=1))
        except Exception, e:
            logging.error("Exception caught in sending start msg to control channel %s: %s" % (exchange, str(e)))
        
