.PHONY: all stop clean

all: clean
	aws-starter --pause-on-error --no-terminate aws-starter.cfg

stop:
	aws-starter --stop aws-starter.cfg

clean:
	rm -f scripts/*.substituted
	rm -f logs/*.log
	rm -f aws-starter.instance_ids
	rm -f ssh/config
