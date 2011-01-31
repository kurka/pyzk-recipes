# Copyright (c) 2010, Henry Robinson
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#     * Neither the name of the <organization> nor the
#       names of its contributors may be used to endorse or promote products
#       derived from this software without specific prior written permission.

# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL <COPYRIGHT HOLDER> BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

# Grupo 03

import zookeeper, threading, sys, time
ZOO_OPEN_ACL_UNSAFE = {"perms":0x1f, "scheme":"world", "id" :"anyone"};

class ZooKeeperQueue(object):
  """
  This is a distributed queue implementation using Apache ZooKeeper.

  See this blog post:
  http://www.cloudera.com/blog/2009/05/building-a-distributed-concurrent-queue-with-apache-zookeeper/

  for more details.
  """
  def __init__(self,queuename, port, is_producer=False):
    self.connected = False
    self.queuename = "/" + queuename
    self.cv = threading.Condition()
    zookeeper.set_log_stream(open("/dev/null"))
    def watcher(handle,type,state,path):
      print "Connected"
      self.cv.acquire()
      self.connected = True
      self.cv.notify()
      self.cv.release()

    self.cv.acquire()
    self.handle = zookeeper.init("localhost:%d" % port, watcher, 10000)
    self.cv.wait(10.0)
    if not self.connected:
      print "Connection to ZooKeeper cluster timed out - is a server running on localhost:%d?" % port
      sys.exit()
    self.cv.release()
    if is_producer:
      try:
        zookeeper.create(self.handle,self.queuename,"queue top level", [ZOO_OPEN_ACL_UNSAFE],0)
        print "Created new Queue, OK"
      except zookeeper.NodeExistsException:
        print "Queue Already Exists"

  def __del__(self):
    zookeeper.close(self.handle)
    print "Zookeeper handle closed and resources freed."

  def enqueue(self,val):
    """
    Adds a new znode whose contents are val to the queue
    """
    zookeeper.create(self.handle, self.queuename+"/item", val, [ZOO_OPEN_ACL_UNSAFE],zookeeper.SEQUENCE)

  def dequeue(self):
    """
    Removes an item from the queue. Returns None is the queue is empty
    when it is read.
    """
    while True:
      children = sorted(zookeeper.get_children(self.handle, self.queuename,None))
      if len(children) == 0:
        return None
      for child in children:
        data = self.get_and_delete(self.queuename + "/" + children[0])
        if data:
          return data

  def get_and_delete(self,node):
    """
    Atomic get-and-delete operation. Returns None on failure.
    """
    try:
      (data,stat) = zookeeper.get(self.handle, node, None)
      zookeeper.delete(self.handle, node, stat["version"])
      return data
    except zookeeper.NoNodeException:
      # Someone deleted the node in between our get and delete
      return None
    except zookeeper.BadVersionException, e:
      # Someone is modifying the queue in place. You can reasonably
      # either retry to re-read the item, or abort.
      print "Queue item %d modified in place, aborting..." % node
      raise e

  def get_and_maintain(self):
      """
      Atomic get-and-maintain operation. Returns None on failure.
      """
      children = sorted(zookeeper.get_children(self.handle, self.queuename,None))
      if len(children) == 0:
        return None
      for child in children:
        node = self.queuename + "/" + children[0]
        if node:
          break
      try:
        (data,stat) = zookeeper.get(self.handle, node, None)
  #       zookeeper.delete(self.handle, node, stat["version"])
        return data
      except zookeeper.NoNodeException:
        # Someone deleted the node in between our get and delete
        return None
      except zookeeper.BadVersionException, e:
        # Someone is modifying the queue in place. You can reasonably
        # either retry to re-read the item, or abort.
        print "Queue item %d modified in place, aborting..." % node
        raise e

  def queue_size(self):
    return len(zookeeper.get_children(self.handle, self.queuename, None))

  def queue_size_of_id(self, id):
    """ Returns how many products of producer ID are there in the queue. """
    children = zookeeper.get_children(self.handle, self.queuename, None)
    if len(children) == 0:
      return 0
    num = 0
    for child in children:
      try:
        (data, stat) = zookeeper.get(self.handle, self.queuename + "/" + child, None)
      except zookeeper.NoNodeException:
        data = None
      if data and data.split()[1] == id:
        num += 1
    return num
      
  def block_dequeue(self):
    """
    Similar to dequeue, but if the queue is empty, block until an item
    is added and successfully removed.
    """
    def queue_watcher(handle,event,state,path):
      self.cv.acquire()
      self.cv.notify()
      self.cv.release()
    while True:
      self.cv.acquire()
      children = sorted(zookeeper.get_children(self.handle, self.queuename, queue_watcher))
      for child in children:
        data = self.get_and_delete(self.queuename+"/"+children[0])
        if data != None:
          self.cv.release()
          return data
        self.cv.wait()
        self.cv.release()

