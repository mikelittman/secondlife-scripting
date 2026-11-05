integer channel = 0;

string greet(string name) {
    return "Hello, " + name;
}

default {
    state_entry() {
        llOwnerSay(greet("world"));
        vector position = <1.0, 2.0, 3.0>;
        if (position.x > 0) {
            llSay(channel, (string)position);
        }
    }

    touch_start(integer total_number) {
        llOwnerSay("touched");
    }
}
