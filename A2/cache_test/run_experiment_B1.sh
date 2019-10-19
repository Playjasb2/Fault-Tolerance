
make clear

# loop through kb
for ((i = 4 ; i <= 1024 ; i += 4 )); do
    echo "block size = ${i} kb"
    echo -n "$i," >> miss_rate_kb.csv
    perf stat -e cache-misses,cache-references ./cache_test -c 1 -k $i 2>&1 | grep 'cache-misses' | awk '{print $4;}' >> miss_rate_kb.csv
done

# loop through mb
for ((i = 1024 ; i <= 32 * 1024 ; i += 512 )); do
    echo "block size = ${i} mb"
    echo -n "$i," >> miss_rate_mb.csv
    perf stat -e cache-misses,cache-references ./cache_test -c 1 -k $i 2>&1 | grep 'cache-misses' | awk '{print $4;}' >> miss_rate_mb.csv
done

echo "
    set terminal png
    set datafile separator ','
    set output 'cache_bandwidth_kb.png'
    set title 'Miss Rate (KB)'
    set xlabel 'Blocksize (KB)'
    set ylabel 'Miss Rate (%)'
    plot 'miss_rate_kb.csv' using 1:2 w lp title 'Bandwidth'
" | gnuplot

echo "
    set terminal png
    set datafile separator ','
    set output 'cache_bandwidth_mb.png'
    set title 'Miss Rate (MB)'
    set xlabel 'Blocksize (MB)'
    set ylabel 'Miss Rate (%)'
    plot 'miss_rate_mb.csv' using 1:2 w lp title 'Bandwidth'
" | gnuplot
