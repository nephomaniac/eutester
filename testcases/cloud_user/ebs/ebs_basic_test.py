#!/usr/bin/env python

#
##########################
#                        #
#       Test Cases       #
#                        #
##########################
#
# [test_ebs_basic_test_suite]
#       Full suite of ebs related tests
#        Test Summary: 
#
#        -create a volume (do this first)
#        -run an instance (do this second, if this fails at least we know we could create a vol)
#        
#        Usage Tests: 
#        -negative -attempt to attach a volume to an instance in a separate cluster. 
#        -attach a single volume to an instance in the zones given, write random data and calc md5 of volumes
#        -negative:attempt to delete the attached instance, should fail
#        -negative:attempt to attach an in-use volume, should fail
#        -attach a 2nd volume to an instance, write random date to vol and calc md5 of volumes
#        -reboot instance
#        -verify both volumes are attached after reboot of instance. 
#        -detach 1st volume
#        -create snapshot of detached volume
#        -create snapshot of attached volume
#        -attempt to create a volume of each snapshot, if within a multi-cluster env do 1 in each cluster 
#        -attempt to attach each volume created from the previous snaps to an instance verify md5s
#        
#        Properties tests:
#        -create a volume of greater than prop size, should fail
#        -create a 2nd volume attempting to exceed the max aggregate size, should fail
#        
#        
#        Cleanup:
#        --remove all volumes, instance, and snapshots created during this test
#
#    @author: clarkmatthew

import unittest
from eutester.eutestcase import EutesterTestCase
from eutester.eutestcase import EutesterTestResult
from ebstestsuite import EbsTestSuite
import argparse
import os

ebssuite = None
zone = None
config_file = None
password = None
credpath = None
keypair = None
group = None
vmtype = None
emi = None


if __name__ == "__main__":
    ## If given command line arguments, use them as test names to launch

    testcase= EutesterTestCase(name='ebs_basic_test')    
    testcase.setup_parser(description="Attempts to test and provide info on focused areas related to Eucalyptus EBS related functionality.", 
                          testlist=False)
    testcase.get_args()
    ebstestsuite= testcase.do_with_args(EbsTestSuite)
    testcase.clean_method = ebstestsuite.clean_created_resources
    testlist = ebstestsuite.ebs_basic_test_suite(run=False)
    ret = testcase.run_test_case_list(testlist)
    testcase.print_test_list_results()
    print "ebs_basic_test exiting:("+str(ret)+")"
    exit(ret)

    
  
